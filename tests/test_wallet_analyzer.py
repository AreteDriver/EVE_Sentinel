"""Tests for WalletAnalyzer."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.analyzers.wallet import WalletAnalyzer
from backend.models.applicant import Applicant, CorpHistoryEntry, WalletEntry
from backend.models.flags import FlagSeverity, RedFlags, YellowFlags


@pytest.fixture
def wallet_analyzer():
    """Create a WalletAnalyzer instance."""
    return WalletAnalyzer()


@pytest.fixture
def base_applicant():
    """Create a basic applicant for testing."""
    now = datetime.now(UTC)
    return Applicant(
        character_id=12345678,
        character_name="Test Pilot",
        corporation_id=98000001,
        corporation_name="Test Corp",
        corp_history=[
            CorpHistoryEntry(
                corporation_id=98000001,
                corporation_name="Test Corp",
                start_date=now - timedelta(days=60),
                end_date=None,
                duration_days=60,
            ),
        ],
    )


class TestWalletAnalyzer:
    """Tests for WalletAnalyzer."""

    @pytest.mark.asyncio
    async def test_empty_wallet_returns_no_flags(self, wallet_analyzer, base_applicant):
        """Empty wallet journal should return no flags."""
        base_applicant.wallet_journal = []
        flags = await wallet_analyzer.analyze(base_applicant)
        assert flags == []

    @pytest.mark.asyncio
    async def test_rmt_pattern_detected(self, wallet_analyzer, base_applicant):
        """Regular same-amount transactions should be flagged as RMT."""
        now = datetime.now(UTC)
        # Create 6 weekly 500M transfers - classic RMT pattern
        base_applicant.wallet_journal = [
            WalletEntry(
                id=i,
                date=now - timedelta(days=i * 7),  # Weekly intervals
                ref_type="player_donation",
                amount=500_000_000,  # 500M ISK
            )
            for i in range(6)
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        red_flags = [f for f in flags if f.severity == FlagSeverity.RED]
        assert any(f.code == RedFlags.RMT_PATTERN for f in red_flags)

    @pytest.mark.asyncio
    async def test_rmt_not_flagged_with_varied_amounts(self, wallet_analyzer, base_applicant):
        """Different amounts should not trigger RMT flag."""
        now = datetime.now(UTC)
        # Create transactions with varying amounts
        base_applicant.wallet_journal = [
            WalletEntry(
                id=i,
                date=now - timedelta(days=i * 7),
                ref_type="player_donation",
                amount=100_000_000 + (i * 50_000_000),  # Varying amounts
            )
            for i in range(6)
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        assert not any(f.code == RedFlags.RMT_PATTERN for f in flags)

    @pytest.mark.asyncio
    async def test_rmt_not_flagged_with_irregular_intervals(self, wallet_analyzer, base_applicant):
        """Same amounts at irregular intervals should not trigger RMT flag."""
        now = datetime.now(UTC)
        # Same amount but wildly irregular intervals (1 day, 30 days, 2 days, etc.)
        irregular_days = [0, 1, 31, 33, 90, 91]
        base_applicant.wallet_journal = [
            WalletEntry(
                id=i,
                date=now - timedelta(days=day),
                ref_type="player_donation",
                amount=500_000_000,
            )
            for i, day in enumerate(irregular_days)
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        # Should not flag as RMT due to irregular intervals
        assert not any(f.code == RedFlags.RMT_PATTERN for f in flags)

    @pytest.mark.asyncio
    async def test_rmt_not_flagged_for_small_amounts(self, wallet_analyzer, base_applicant):
        """Small transactions (under 100M) should not trigger RMT even if regular."""
        now = datetime.now(UTC)
        # Regular small donations (like corp reimbursements)
        base_applicant.wallet_journal = [
            WalletEntry(
                id=i,
                date=now - timedelta(days=i * 7),
                ref_type="player_donation",
                amount=10_000_000,  # 10M ISK - too small
            )
            for i in range(6)
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        assert not any(f.code == RedFlags.RMT_PATTERN for f in flags)

    @pytest.mark.asyncio
    async def test_rmt_not_flagged_for_few_transactions(self, wallet_analyzer, base_applicant):
        """Less than 5 same-amount transactions should not trigger RMT."""
        now = datetime.now(UTC)
        # Only 4 transactions (threshold is 5)
        base_applicant.wallet_journal = [
            WalletEntry(
                id=i,
                date=now - timedelta(days=i * 7),
                ref_type="player_donation",
                amount=500_000_000,
            )
            for i in range(4)
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        assert not any(f.code == RedFlags.RMT_PATTERN for f in flags)

    @pytest.mark.asyncio
    async def test_large_pre_join_transfer_detected(self, wallet_analyzer, base_applicant):
        """Large ISK transfer before joining corp should be flagged."""
        now = datetime.now(UTC)
        join_date = now - timedelta(days=60)

        # 1.5B ISK transfer 10 days before joining
        base_applicant.wallet_journal = [
            WalletEntry(
                id=1,
                date=join_date - timedelta(days=10),
                ref_type="player_donation",
                amount=1_500_000_000,  # 1.5B ISK
            ),
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.LARGE_PRE_JOIN_TRANSFER for f in yellow_flags)

    @pytest.mark.asyncio
    async def test_multiple_pre_join_transfers_summed(self, wallet_analyzer, base_applicant):
        """Multiple transfers before joining should be summed."""
        now = datetime.now(UTC)
        join_date = now - timedelta(days=60)

        # Two 600M transfers (1.2B total)
        base_applicant.wallet_journal = [
            WalletEntry(
                id=1,
                date=join_date - timedelta(days=10),
                ref_type="player_donation",
                amount=600_000_000,
            ),
            WalletEntry(
                id=2,
                date=join_date - timedelta(days=5),
                ref_type="player_donation",
                amount=600_000_000,
            ),
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        yellow_flags = [f for f in flags if f.severity == FlagSeverity.YELLOW]
        assert any(f.code == YellowFlags.LARGE_PRE_JOIN_TRANSFER for f in yellow_flags)
        # Check evidence shows correct total
        flag = next(f for f in yellow_flags if f.code == YellowFlags.LARGE_PRE_JOIN_TRANSFER)
        assert flag.evidence["total_isk"] == 1_200_000_000

    @pytest.mark.asyncio
    async def test_pre_join_transfer_not_flagged_if_small(self, wallet_analyzer, base_applicant):
        """Transfers under 1B before joining should not be flagged."""
        now = datetime.now(UTC)
        join_date = now - timedelta(days=60)

        # 500M transfer - under threshold
        base_applicant.wallet_journal = [
            WalletEntry(
                id=1,
                date=join_date - timedelta(days=10),
                ref_type="player_donation",
                amount=500_000_000,  # Only 500M
            ),
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        assert not any(f.code == YellowFlags.LARGE_PRE_JOIN_TRANSFER for f in flags)

    @pytest.mark.asyncio
    async def test_pre_join_transfer_not_flagged_outside_window(self, wallet_analyzer, base_applicant):
        """Transfers more than 30 days before joining should not be flagged."""
        now = datetime.now(UTC)
        join_date = now - timedelta(days=60)

        # 2B transfer 45 days before joining (outside 30-day window)
        base_applicant.wallet_journal = [
            WalletEntry(
                id=1,
                date=join_date - timedelta(days=45),
                ref_type="player_donation",
                amount=2_000_000_000,
            ),
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        assert not any(f.code == YellowFlags.LARGE_PRE_JOIN_TRANSFER for f in flags)

    @pytest.mark.asyncio
    async def test_no_corp_history_skips_pre_join_check(self, wallet_analyzer, base_applicant):
        """Without corp history, pre-join check should be skipped gracefully."""
        now = datetime.now(UTC)
        base_applicant.corp_history = []
        base_applicant.wallet_journal = [
            WalletEntry(
                id=1,
                date=now - timedelta(days=10),
                ref_type="player_donation",
                amount=2_000_000_000,
            ),
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        # Should not crash and should not flag pre-join transfer
        assert not any(f.code == YellowFlags.LARGE_PRE_JOIN_TRANSFER for f in flags)

    @pytest.mark.asyncio
    async def test_normal_gameplay_not_flagged(self, wallet_analyzer, base_applicant):
        """Normal gameplay transactions should not trigger any flags."""
        now = datetime.now(UTC)
        # Mix of bounties, market, and normal player trades
        base_applicant.wallet_journal = [
            WalletEntry(
                id=1,
                date=now - timedelta(days=1),
                ref_type="bounty_prizes",
                amount=50_000_000,
            ),
            WalletEntry(
                id=2,
                date=now - timedelta(days=2),
                ref_type="market_escrow",
                amount=-200_000_000,  # Outgoing
            ),
            WalletEntry(
                id=3,
                date=now - timedelta(days=5),
                ref_type="player_trading",
                amount=300_000_000,
            ),
            WalletEntry(
                id=4,
                date=now - timedelta(days=10),
                ref_type="insurance",
                amount=100_000_000,
            ),
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        # No flags for normal gameplay
        assert len(flags) == 0

    @pytest.mark.asyncio
    async def test_requires_auth_flag_set(self, wallet_analyzer):
        """WalletAnalyzer should indicate it requires auth data."""
        assert wallet_analyzer.requires_auth is True

    @pytest.mark.asyncio
    async def test_analyzer_name_and_description(self, wallet_analyzer):
        """Verify analyzer metadata."""
        assert wallet_analyzer.name == "wallet"
        assert "wallet" in wallet_analyzer.description.lower()

    @pytest.mark.asyncio
    async def test_contract_payments_count_for_rmt(self, wallet_analyzer, base_applicant):
        """Contract payments should also be checked for RMT patterns."""
        now = datetime.now(UTC)
        # Regular contract payments - could be RMT disguised as contracts
        base_applicant.wallet_journal = [
            WalletEntry(
                id=i,
                date=now - timedelta(days=i * 7),
                ref_type="contract_price",
                amount=500_000_000,
            )
            for i in range(6)
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        red_flags = [f for f in flags if f.severity == FlagSeverity.RED]
        assert any(f.code == RedFlags.RMT_PATTERN for f in red_flags)

    @pytest.mark.asyncio
    async def test_outgoing_transfers_not_flagged(self, wallet_analyzer, base_applicant):
        """Outgoing transfers (negative amounts) should not trigger RMT flags."""
        now = datetime.now(UTC)
        # Regular outgoing payments
        base_applicant.wallet_journal = [
            WalletEntry(
                id=i,
                date=now - timedelta(days=i * 7),
                ref_type="player_donation",
                amount=-500_000_000,  # Negative = outgoing
            )
            for i in range(6)
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        assert not any(f.code == RedFlags.RMT_PATTERN for f in flags)

    @pytest.mark.asyncio
    async def test_evidence_includes_dates(self, wallet_analyzer, base_applicant):
        """RMT flag evidence should include transaction dates."""
        now = datetime.now(UTC)
        base_applicant.wallet_journal = [
            WalletEntry(
                id=i,
                date=now - timedelta(days=i * 7),
                ref_type="player_donation",
                amount=500_000_000,
            )
            for i in range(6)
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        rmt_flag = next((f for f in flags if f.code == RedFlags.RMT_PATTERN), None)
        assert rmt_flag is not None
        assert "dates" in rmt_flag.evidence
        assert len(rmt_flag.evidence["dates"]) > 0

    @pytest.mark.asyncio
    async def test_pre_join_evidence_includes_join_date(self, wallet_analyzer, base_applicant):
        """Pre-join flag evidence should include the join date."""
        now = datetime.now(UTC)
        join_date = now - timedelta(days=60)

        base_applicant.wallet_journal = [
            WalletEntry(
                id=1,
                date=join_date - timedelta(days=10),
                ref_type="player_donation",
                amount=2_000_000_000,
            ),
        ]

        flags = await wallet_analyzer.analyze(base_applicant)

        pre_join_flag = next(
            (f for f in flags if f.code == YellowFlags.LARGE_PRE_JOIN_TRANSFER), None
        )
        assert pre_join_flag is not None
        assert "join_date" in pre_join_flag.evidence
        assert "total_isk" in pre_join_flag.evidence
