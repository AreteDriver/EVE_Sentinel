"""Background scheduler for automated tasks."""

import asyncio

from backend.analyzers.risk_scorer import RiskScorer
from backend.config import settings
from backend.connectors.esi import ESIClient
from backend.connectors.zkill import ZKillClient
from backend.database import (
    AuditLogRepository,
    ReportRepository,
    WatchlistRepository,
    get_session,
)
from backend.logging_config import get_logger

logger = get_logger(__name__)


class ReanalysisScheduler:
    """
    Background scheduler for automated watchlist re-analysis.

    Periodically checks the watchlist for characters needing re-analysis
    and automatically runs analysis on them.
    """

    def __init__(
        self,
        interval_minutes: int = 60,
        max_analyses_per_run: int = 10,
    ) -> None:
        self._interval_minutes = interval_minutes
        self._max_analyses_per_run = max_analyses_per_run
        self._running = False
        self._task: asyncio.Task | None = None

        # Initialize clients
        self._esi_client = ESIClient()
        self._zkill_client = ZKillClient()
        self._risk_scorer = RiskScorer()

    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Reanalysis scheduler started (interval: {self._interval_minutes} minutes)")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Reanalysis scheduler stopped")

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                await self._run_reanalysis()
            except Exception as e:
                logger.error(f"Error in reanalysis run: {e}")

            # Wait for next interval
            await asyncio.sleep(self._interval_minutes * 60)

    async def _run_reanalysis(self) -> None:
        """Run a single reanalysis cycle."""
        logger.info("Starting scheduled reanalysis cycle")

        async with get_session() as session:
            watchlist_repo = WatchlistRepository(session)
            report_repo = ReportRepository(session)
            audit_repo = AuditLogRepository(session)

            # Get characters needing reanalysis
            characters = await watchlist_repo.list_needing_reanalysis()

            if not characters:
                logger.info("No characters need reanalysis")
                return

            logger.info(f"Found {len(characters)} characters needing reanalysis")

            # Limit to max per run
            to_analyze = characters[: self._max_analyses_per_run]

            success_count = 0
            fail_count = 0

            for entry in to_analyze:
                try:
                    logger.info(f"Reanalyzing {entry.character_name} ({entry.character_id})")

                    # Run analysis
                    applicant = await self._esi_client.build_applicant(entry.character_id)
                    applicant = await self._zkill_client.enrich_applicant(applicant)
                    report = await self._risk_scorer.analyze(applicant)

                    # Save report
                    await report_repo.save(report)

                    # Update watchlist entry
                    await watchlist_repo.update_analysis(
                        character_id=entry.character_id,
                        report_id=report.report_id,
                        risk_level=report.overall_risk.value,
                    )

                    # Check for risk level change
                    if (
                        entry.alert_on_change
                        and entry.last_risk_level
                        and entry.last_risk_level != report.overall_risk.value
                    ):
                        await self._handle_risk_change(entry, report.overall_risk.value)

                    success_count += 1

                except Exception as e:
                    logger.error(f"Failed to reanalyze {entry.character_name}: {e}")
                    fail_count += 1

            # Log the batch run
            await audit_repo.log(
                action="batch_analyze",
                user_id="scheduler",
                user_name="Automated Scheduler",
                target_type="watchlist",
                details={
                    "trigger": "scheduled_reanalysis",
                    "character_count": len(to_analyze),
                    "success_count": success_count,
                    "fail_count": fail_count,
                },
            )

            logger.info(f"Reanalysis cycle complete: {success_count} success, {fail_count} failed")

    async def _handle_risk_change(self, entry, new_risk_level: str) -> None:
        """Handle a risk level change (send notifications)."""
        logger.info(
            f"Risk level changed for {entry.character_name}: "
            f"{entry.last_risk_level} -> {new_risk_level}"
        )

        # Check if change meets alert threshold
        should_alert = False
        if entry.alert_threshold == "any":
            should_alert = True
        elif entry.alert_threshold == "yellow" and new_risk_level in [
            "YELLOW",
            "RED",
        ]:
            should_alert = True
        elif entry.alert_threshold == "red" and new_risk_level == "RED":
            should_alert = True

        if should_alert:
            base_url = settings.base_url or "http://localhost:8000"

            async with get_session() as session:
                report_repo = ReportRepository(session)
                report = await report_repo.get_latest_by_character_id(entry.character_id)

                if not report:
                    return

                # Send webhook notification if configured
                try:
                    from backend.webhooks import DiscordWebhook

                    if settings.discord_webhook_url:
                        webhook = DiscordWebhook()
                        await webhook.send_report(report, base_url=base_url)
                except Exception as e:
                    logger.error(f"Failed to send Discord notification: {e}")

                # Send email notifications to users with email enabled
                try:
                    from backend.database.repository import UserRepository
                    from backend.services.email_service import email_service

                    if email_service.is_configured():
                        user_repo = UserRepository(session)
                        users = await user_repo.get_users_for_email_alert(
                            alert_type="watchlist_change",
                            risk_level=new_risk_level,
                        )

                        for user in users:
                            if user.email:
                                email_service.send_risk_change_alert(
                                    to_email=user.email,
                                    character_name=entry.character_name,
                                    character_id=entry.character_id,
                                    old_risk=entry.last_risk_level,
                                    new_risk=new_risk_level,
                                    report=report,
                                    base_url=base_url,
                                )
                except Exception as e:
                    logger.error(f"Failed to send email notifications: {e}")

    async def run_manual(self, character_ids: list[int] | None = None) -> dict:
        """
        Run manual reanalysis for specific characters or all needing reanalysis.

        Returns statistics about the run.
        """
        async with get_session() as session:
            watchlist_repo = WatchlistRepository(session)
            report_repo = ReportRepository(session)

            if character_ids:
                # Get specific characters
                characters = []
                for char_id in character_ids:
                    entry = await watchlist_repo.get_by_character_id(char_id)
                    if entry:
                        characters.append(entry)
            else:
                # Get all needing reanalysis
                characters = await watchlist_repo.list_needing_reanalysis()

            if not characters:
                return {"analyzed": 0, "success": 0, "failed": 0}

            success_count = 0
            fail_count = 0

            for entry in characters:
                try:
                    applicant = await self._esi_client.build_applicant(entry.character_id)
                    applicant = await self._zkill_client.enrich_applicant(applicant)
                    report = await self._risk_scorer.analyze(applicant)

                    await report_repo.save(report)
                    await watchlist_repo.update_analysis(
                        character_id=entry.character_id,
                        report_id=report.report_id,
                        risk_level=report.overall_risk.value,
                    )

                    success_count += 1
                except Exception as e:
                    logger.error(f"Manual reanalysis failed for {entry.character_id}: {e}")
                    fail_count += 1

            return {
                "analyzed": len(characters),
                "success": success_count,
                "failed": fail_count,
            }


# Global scheduler instance
scheduler = ReanalysisScheduler(
    interval_minutes=60,  # Run every hour
    max_analyses_per_run=10,  # Limit to 10 per run to avoid rate limits
)
