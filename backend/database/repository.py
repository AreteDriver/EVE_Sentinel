"""Repository for report persistence operations."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import ReportRecord
from backend.models.applicant import Applicant, Playstyle, SuspectedAlt
from backend.models.flags import RiskFlag
from backend.models.report import AnalysisReport, OverallRisk, ReportStatus, ReportSummary


class ReportRepository:
    """
    Async repository for AnalysisReport persistence.

    Handles conversion between Pydantic models and SQLAlchemy ORM.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, report: AnalysisReport) -> None:
        """Save or update an analysis report."""
        record = self._to_record(report)
        await self._session.merge(record)
        await self._session.commit()

    async def get_by_id(self, report_id: UUID) -> AnalysisReport | None:
        """Retrieve a report by its UUID."""
        stmt = select(ReportRecord).where(ReportRecord.report_id == str(report_id))
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_model(record) if record else None

    async def get_by_character_id(
        self,
        character_id: int,
        limit: int = 10,
    ) -> list[AnalysisReport]:
        """Get reports for a character, newest first."""
        stmt = (
            select(ReportRecord)
            .where(ReportRecord.character_id == character_id)
            .order_by(desc(ReportRecord.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_model(r) for r in records]

    async def get_latest_by_character_id(
        self,
        character_id: int,
    ) -> AnalysisReport | None:
        """Get the most recent report for a character."""
        reports = await self.get_by_character_id(character_id, limit=1)
        return reports[0] if reports else None

    async def list_reports(
        self,
        limit: int = 50,
        offset: int = 0,
        risk_filter: OverallRisk | None = None,
    ) -> list[ReportSummary]:
        """List report summaries with optional filtering."""
        stmt = select(ReportRecord).order_by(desc(ReportRecord.created_at))

        if risk_filter:
            stmt = stmt.where(ReportRecord.overall_risk == risk_filter.value)

        stmt = stmt.offset(offset).limit(limit)

        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_summary(r) for r in records]

    async def count_reports(self, risk_filter: OverallRisk | None = None) -> int:
        """Count total reports with optional filtering."""
        stmt = select(func.count(ReportRecord.report_id))
        if risk_filter:
            stmt = stmt.where(ReportRecord.overall_risk == risk_filter.value)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def delete_by_id(self, report_id: UUID) -> bool:
        """Delete a report by ID. Returns True if deleted."""
        stmt = select(ReportRecord).where(ReportRecord.report_id == str(report_id))
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            await self._session.delete(record)
            await self._session.commit()
            return True
        return False

    async def get_reports_by_date_range(
        self,
        days: int = 30,
    ) -> list[dict]:
        """
        Get report counts grouped by date for the last N days.

        Returns a list of dicts with date and counts by risk level.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)

        stmt = (
            select(ReportRecord)
            .where(ReportRecord.created_at >= cutoff)
            .order_by(ReportRecord.created_at)
        )
        result = await self._session.execute(stmt)
        records = result.scalars().all()

        # Group by date
        date_counts: dict[str, dict[str, int]] = {}
        for record in records:
            date_str = record.created_at.strftime("%Y-%m-%d")
            if date_str not in date_counts:
                date_counts[date_str] = {"red": 0, "yellow": 0, "green": 0, "total": 0}
            risk = record.overall_risk.lower()
            if risk in date_counts[date_str]:
                date_counts[date_str][risk] += 1
            date_counts[date_str]["total"] += 1

        # Convert to list sorted by date
        return [
            {"date": date, **counts}
            for date, counts in sorted(date_counts.items())
        ]

    async def get_top_flags(self, limit: int = 10) -> list[dict]:
        """
        Get the most common flags across all reports.

        Returns a list of dicts with flag code and count.
        """
        # Get all reports with flags
        stmt = select(ReportRecord.flags_json).where(
            ReportRecord.flags_json.isnot(None)
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        # Count flags
        flag_counts: dict[str, dict] = {}
        for (flags_json,) in rows:
            if flags_json:
                flags = json.loads(flags_json)
                for flag in flags:
                    code = flag.get("code", "UNKNOWN")
                    if code not in flag_counts:
                        flag_counts[code] = {
                            "code": code,
                            "title": flag.get("title", code),
                            "severity": flag.get("severity", "info"),
                            "count": 0,
                        }
                    flag_counts[code]["count"] += 1

        # Sort by count and return top N
        sorted_flags = sorted(flag_counts.values(), key=lambda x: x["count"], reverse=True)
        return sorted_flags[:limit]

    async def get_recent_activity(self, days: int = 7) -> dict:
        """
        Get activity summary for recent days.

        Returns count of reports analyzed per day.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = select(func.count(ReportRecord.report_id)).where(
            ReportRecord.created_at >= cutoff
        )
        result = await self._session.execute(stmt)
        recent_count = result.scalar() or 0

        return {
            "reports_last_7_days": recent_count,
            "avg_per_day": round(recent_count / days, 1) if days > 0 else 0,
        }

    # --- Conversion methods ---

    def _to_record(self, report: AnalysisReport) -> ReportRecord:
        """Convert Pydantic model to SQLAlchemy record."""
        return ReportRecord(
            report_id=str(report.report_id),
            character_id=report.character_id,
            character_name=report.character_name,
            overall_risk=report.overall_risk.value,
            confidence=report.confidence,
            status=report.status.value,
            created_at=report.created_at,
            completed_at=report.completed_at,
            requested_by=report.requested_by,
            processing_time_ms=report.processing_time_ms,
            red_flag_count=report.red_flag_count,
            yellow_flag_count=report.yellow_flag_count,
            green_flag_count=report.green_flag_count,
            flags_json=json.dumps([f.model_dump(mode="json") for f in report.flags]),
            recommendations_json=json.dumps(report.recommendations),
            analyzers_run_json=json.dumps(report.analyzers_run),
            errors_json=json.dumps(report.errors),
            applicant_data_json=(
                report.applicant_data.model_dump_json() if report.applicant_data else None
            ),
            playstyle_json=(report.playstyle.model_dump_json() if report.playstyle else None),
            suspected_alts_json=json.dumps(
                [a.model_dump(mode="json") for a in report.suspected_alts]
            ),
        )

    def _to_model(self, record: ReportRecord) -> AnalysisReport:
        """Convert SQLAlchemy record to Pydantic model."""
        return AnalysisReport(
            report_id=UUID(record.report_id),
            character_id=record.character_id,
            character_name=record.character_name,
            overall_risk=OverallRisk(record.overall_risk),
            confidence=record.confidence,
            status=ReportStatus(record.status),
            created_at=record.created_at,
            completed_at=record.completed_at,
            requested_by=record.requested_by,
            processing_time_ms=record.processing_time_ms,
            red_flag_count=record.red_flag_count,
            yellow_flag_count=record.yellow_flag_count,
            green_flag_count=record.green_flag_count,
            flags=[RiskFlag.model_validate(f) for f in json.loads(record.flags_json)],
            recommendations=json.loads(record.recommendations_json),
            analyzers_run=json.loads(record.analyzers_run_json),
            errors=json.loads(record.errors_json),
            applicant_data=(
                Applicant.model_validate_json(record.applicant_data_json)
                if record.applicant_data_json
                else None
            ),
            playstyle=(
                Playstyle.model_validate_json(record.playstyle_json)
                if record.playstyle_json
                else None
            ),
            suspected_alts=[
                SuspectedAlt.model_validate(a) for a in json.loads(record.suspected_alts_json)
            ],
        )

    def _to_summary(self, record: ReportRecord) -> ReportSummary:
        """Convert record to lightweight summary."""
        return ReportSummary(
            report_id=UUID(record.report_id),
            character_id=record.character_id,
            character_name=record.character_name,
            overall_risk=OverallRisk(record.overall_risk),
            confidence=record.confidence,
            red_flag_count=record.red_flag_count,
            yellow_flag_count=record.yellow_flag_count,
            green_flag_count=record.green_flag_count,
            created_at=record.created_at,
            status=ReportStatus(record.status),
        )
