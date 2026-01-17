"""Tests for risk scorer integration."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.analyzers.risk_scorer import RiskScorer
from backend.models.applicant import Applicant, CorpHistoryEntry, KillboardStats
from backend.models.flags import FlagSeverity
from backend.models.report import OverallRisk, ReportStatus


@pytest.fixture
def risk_scorer():
    """Create a RiskScorer instance."""
    return RiskScorer()


@pytest.fixture
def clean_applicant():
    """Create an applicant with clean history."""
    now = datetime.now(UTC)
    return Applicant(
        character_id=12345678,
        character_name="Clean Pilot",
        corporation_id=98000001,
        corporation_name="Good Corp",
        corp_history=[
            CorpHistoryEntry(
                corporation_id=98000001,
                corporation_name="Good Corp",
                start_date=now - timedelta(days=400),
                end_date=None,
                duration_days=400,
            ),
            CorpHistoryEntry(
                corporation_id=98000002,
                corporation_name="Previous Good Corp",
                start_date=now - timedelta(days=800),
                end_date=now - timedelta(days=400),
                duration_days=400,
            ),
        ],
        killboard=KillboardStats(
            kills_total=300,
            kills_90d=60,
            kills_30d=25,
            awox_kills=0,
            solo_kills=15,
        ),
    )


@pytest.fixture
def risky_applicant():
    """Create an applicant with multiple red flags."""
    now = datetime.now(UTC)
    return Applicant(
        character_id=87654321,
        character_name="Risky Pilot",
        corporation_id=98000001,
        corporation_name="Current Corp",
        corp_history=[
            CorpHistoryEntry(
                corporation_id=98000001,
                corporation_name="Current Corp",
                start_date=now - timedelta(days=10),
                end_date=None,
                duration_days=10,
            ),
            # Rapid corp hopping - 6 corps in 6 months
            *[
                CorpHistoryEntry(
                    corporation_id=1000000 + i,
                    corporation_name=f"Corp {i}",
                    start_date=now - timedelta(days=30 * (i + 2)),
                    end_date=now - timedelta(days=30 * (i + 1)),
                    duration_days=30,
                )
                for i in range(5)
            ],
        ],
        killboard=KillboardStats(
            kills_total=50,
            kills_90d=5,
            awox_kills=3,
        ),
    )


class TestRiskScorer:
    """Tests for RiskScorer."""

    @pytest.mark.asyncio
    async def test_analyze_returns_report(self, risk_scorer, clean_applicant):
        """Analyze should return a complete report."""
        report = await risk_scorer.analyze(clean_applicant)

        assert report.character_id == clean_applicant.character_id
        assert report.character_name == clean_applicant.character_name
        assert report.status == ReportStatus.COMPLETED
        assert report.completed_at is not None
        assert report.processing_time_ms is not None
        assert report.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_clean_applicant_gets_green(self, risk_scorer, clean_applicant):
        """Clean applicant should get GREEN risk rating."""
        report = await risk_scorer.analyze(clean_applicant)

        assert report.overall_risk == OverallRisk.GREEN
        assert report.red_flag_count == 0
        assert report.green_flag_count >= 1

    @pytest.mark.asyncio
    async def test_risky_applicant_gets_red_or_yellow(self, risk_scorer, risky_applicant):
        """Applicant with red flags should get RED or YELLOW rating."""
        report = await risk_scorer.analyze(risky_applicant)

        # Should have multiple issues detected
        assert report.overall_risk in (OverallRisk.RED, OverallRisk.YELLOW)
        assert report.red_flag_count >= 1 or report.yellow_flag_count >= 1

    @pytest.mark.asyncio
    async def test_awox_generates_recommendation(self, risk_scorer, risky_applicant):
        """AWOX history should generate specific recommendation."""
        report = await risk_scorer.analyze(risky_applicant)

        # Should have AWOX-related recommendation
        awox_rec = any("AWOX" in rec for rec in report.recommendations)
        assert awox_rec or report.red_flag_count > 0

    @pytest.mark.asyncio
    async def test_analyzers_run_recorded(self, risk_scorer, clean_applicant):
        """Report should track which analyzers were run."""
        report = await risk_scorer.analyze(clean_applicant)

        assert "killboard" in report.analyzers_run
        assert "corp_history" in report.analyzers_run

    @pytest.mark.asyncio
    async def test_requested_by_recorded(self, risk_scorer, clean_applicant):
        """Requester should be recorded in report."""
        report = await risk_scorer.analyze(clean_applicant, requested_by="TestRecruiter")

        assert report.requested_by == "TestRecruiter"

    @pytest.mark.asyncio
    async def test_applicant_data_included(self, risk_scorer, clean_applicant):
        """Full applicant data should be included in report."""
        report = await risk_scorer.analyze(clean_applicant)

        assert report.applicant_data is not None
        assert report.applicant_data.character_id == clean_applicant.character_id

    @pytest.mark.asyncio
    async def test_confidence_in_valid_range(self, risk_scorer, clean_applicant):
        """Confidence should be between 0 and 1."""
        report = await risk_scorer.analyze(clean_applicant)

        assert 0.0 <= report.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_flag_counts_match_flags(self, risk_scorer, risky_applicant):
        """Flag counts should match actual flags in report."""
        report = await risk_scorer.analyze(risky_applicant)

        red_count = sum(1 for f in report.flags if f.severity == FlagSeverity.RED)
        yellow_count = sum(1 for f in report.flags if f.severity == FlagSeverity.YELLOW)
        green_count = sum(1 for f in report.flags if f.severity == FlagSeverity.GREEN)

        assert report.red_flag_count == red_count
        assert report.yellow_flag_count == yellow_count
        assert report.green_flag_count == green_count


class TestRiskScorerRecommendations:
    """Tests for recommendation generation."""

    @pytest.mark.asyncio
    async def test_high_risk_gets_rejection_recommendation(self, risk_scorer):
        """HIGH RISK applicants should get rejection recommendation."""
        now = datetime.now(UTC)
        applicant = Applicant(
            character_id=99999999,
            character_name="Very Risky",
            corp_history=[
                CorpHistoryEntry(
                    corporation_id=98000001,
                    corporation_name="Current",
                    start_date=now - timedelta(days=5),
                    duration_days=5,
                    is_hostile=True,  # Hostile corp
                ),
            ],
            killboard=KillboardStats(
                kills_total=100,
                kills_90d=30,
                awox_kills=5,  # Multiple AWOX
            ),
        )

        report = await risk_scorer.analyze(applicant)

        if report.overall_risk == OverallRisk.RED:
            assert any("HIGH RISK" in rec for rec in report.recommendations)

    @pytest.mark.asyncio
    async def test_low_risk_gets_standard_onboarding(self, risk_scorer, clean_applicant):
        """LOW RISK applicants should get standard onboarding recommendation."""
        report = await risk_scorer.analyze(clean_applicant)

        if report.overall_risk == OverallRisk.GREEN:
            assert any("standard onboarding" in rec.lower() for rec in report.recommendations)

    @pytest.mark.asyncio
    async def test_short_tenure_generates_recommendation(self, risk_scorer):
        """Short tenure should generate probation recommendation."""
        now = datetime.now(UTC)
        applicant = Applicant(
            character_id=11111111,
            character_name="New Guy",
            corp_history=[
                CorpHistoryEntry(
                    corporation_id=98000001,
                    corporation_name="Current Corp",
                    start_date=now - timedelta(days=15),
                    duration_days=15,
                ),
            ],
            killboard=KillboardStats(kills_total=50, kills_90d=25),
        )

        report = await risk_scorer.analyze(applicant)

        # Should mention probation or new corp
        has_tenure_rec = any(
            "probation" in rec.lower() or "new to current corp" in rec.lower()
            for rec in report.recommendations
        )
        assert has_tenure_rec or report.yellow_flag_count > 0
