"""Aggregate risk scorer that combines all analyzers."""

import asyncio
import time
from datetime import UTC, datetime

from backend.models.applicant import Applicant
from backend.models.flags import RiskFlag
from backend.models.report import AnalysisReport, OverallRisk, ReportStatus

from .activity import ActivityAnalyzer
from .base import BaseAnalyzer
from .corp_history import CorpHistoryAnalyzer
from .killboard import KillboardAnalyzer
from .wallet import WalletAnalyzer


class RiskScorer:
    """
    Orchestrates all analyzers and produces final risk assessment.

    This is the main entry point for character analysis. It:
    1. Runs all registered analyzers
    2. Collects and deduplicates flags
    3. Calculates overall risk score
    4. Generates recommendations
    """

    def __init__(self) -> None:
        self.analyzers: list[BaseAnalyzer] = [
            KillboardAnalyzer(),
            CorpHistoryAnalyzer(),
            WalletAnalyzer(),
            ActivityAnalyzer(),
            # Add more analyzers as they're implemented:
            # AssetsAnalyzer(),
            # SocialAnalyzer(),
        ]

    async def analyze(
        self,
        applicant: Applicant,
        requested_by: str | None = None,
    ) -> AnalysisReport:
        """
        Run full analysis on an applicant.

        Args:
            applicant: The applicant to analyze
            requested_by: Who requested this analysis

        Returns:
            Complete analysis report
        """
        start_time = time.monotonic()

        report = AnalysisReport(
            character_id=applicant.character_id,
            character_name=applicant.character_name,
            status=ReportStatus.PROCESSING,
            requested_by=requested_by,
        )

        all_flags: list[RiskFlag] = []
        errors: list[str] = []

        # Run all analyzers concurrently
        tasks = [self._run_analyzer(analyzer, applicant) for analyzer in self.analyzers]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for analyzer, result in zip(self.analyzers, results):
            if isinstance(result, BaseException):
                errors.append(f"{analyzer.name}: {str(result)}")
            else:
                all_flags.extend(result)
                report.analyzers_run.append(analyzer.name)

        # Store flags and calculate risk
        report.flags = all_flags
        report.errors = errors
        report.calculate_risk()

        # Extract playstyle if we have one
        report.playstyle = applicant.playstyle
        report.suspected_alts = applicant.suspected_alts

        # Generate recommendations
        report.recommendations = self._generate_recommendations(report)

        # Store full applicant data
        report.applicant_data = applicant

        # Finalize
        report.status = ReportStatus.COMPLETED
        report.completed_at = datetime.now(UTC)
        report.processing_time_ms = int((time.monotonic() - start_time) * 1000)

        return report

    async def _run_analyzer(
        self,
        analyzer: BaseAnalyzer,
        applicant: Applicant,
    ) -> list[RiskFlag]:
        """Run a single analyzer with error handling."""
        try:
            return await analyzer.analyze(applicant)
        except Exception as e:
            # Log error but don't fail the whole analysis
            raise RuntimeError(f"Analyzer {analyzer.name} failed: {e}") from e

    def _generate_recommendations(self, report: AnalysisReport) -> list[str]:
        """Generate actionable recommendations based on flags."""
        recommendations: list[str] = []

        # Check for specific flag patterns
        flag_codes = {f.code for f in report.flags}

        if "KNOWN_SPY_CORP" in flag_codes:
            recommendations.append(
                "Verify reason for leaving hostile organization - request explanation"
            )

        if "AWOX_HISTORY" in flag_codes:
            recommendations.append(
                "Review AWOX kills in detail - may be structure bashing or valid kills"
            )

        if "RAPID_CORP_HOP" in flag_codes:
            recommendations.append(
                "Investigate rapid corp changes - may indicate instability or spy behavior"
            )

        if "RMT_PATTERN" in flag_codes:
            recommendations.append(
                "Potential RMT detected - regular same-amount transfers suggest bought ISK"
            )

        if "LARGE_PRE_JOIN_TRANSFER" in flag_codes:
            recommendations.append(
                "Large ISK transfer before joining - investigate source and purpose"
            )

        if "LOW_ACTIVITY" in flag_codes:
            recommendations.append(
                "Verify pilot is active and will contribute - check recent login history"
            )

        if "SHORT_TENURE" in flag_codes:
            recommendations.append("New to current corp - consider probationary period")

        if report.suspected_alts:
            recommendations.append(
                f"Potential undeclared alts detected ({len(report.suspected_alts)}) - "
                "request disclosure"
            )

        if report.overall_risk == OverallRisk.RED:
            recommendations.insert(0, "HIGH RISK - Recommend rejection or extensive vetting")
        elif report.overall_risk == OverallRisk.YELLOW:
            recommendations.insert(0, "MODERATE RISK - Additional review recommended")
        elif report.overall_risk == OverallRisk.GREEN:
            recommendations.append("Low risk indicators - standard onboarding appropriate")

        if not recommendations:
            recommendations.append("No specific concerns identified")

        return recommendations

    def register_analyzer(self, analyzer: BaseAnalyzer) -> None:
        """Register an additional analyzer."""
        self.analyzers.append(analyzer)

    def list_analyzers(self) -> list[str]:
        """List all registered analyzers."""
        return [a.name for a in self.analyzers]
