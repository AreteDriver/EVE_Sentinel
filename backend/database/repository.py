"""Repository for report persistence operations."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import AnnotationRecord, ReportRecord
from backend.models.applicant import Applicant, Playstyle, SuspectedAlt
from backend.models.flags import RiskFlag
from backend.models.report import AnalysisReport, OverallRisk, ReportStatus, ReportSummary


class Annotation(BaseModel):
    """Pydantic model for annotation data."""

    id: int
    report_id: str
    author: str
    content: str
    annotation_type: str = "note"
    created_at: datetime
    updated_at: datetime | None = None


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

    async def search_reports(
        self,
        query: str | None = None,
        risk_filter: OverallRisk | None = None,
        flag_code: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ReportSummary]:
        """
        Search reports with multiple filters.

        Args:
            query: Search term for character name (case-insensitive partial match)
            risk_filter: Filter by risk level
            flag_code: Filter by specific flag code
            date_from: Filter reports created after this date
            date_to: Filter reports created before this date
            limit: Maximum results to return
            offset: Pagination offset
        """
        stmt = select(ReportRecord).order_by(desc(ReportRecord.created_at))

        # Character name search (case-insensitive)
        if query:
            stmt = stmt.where(
                ReportRecord.character_name.ilike(f"%{query}%")
            )

        # Risk level filter
        if risk_filter:
            stmt = stmt.where(ReportRecord.overall_risk == risk_filter.value)

        # Flag code filter (search in JSON)
        if flag_code:
            stmt = stmt.where(
                ReportRecord.flags_json.contains(f'"code": "{flag_code}"')
            )

        # Date range filters
        if date_from:
            stmt = stmt.where(ReportRecord.created_at >= date_from)
        if date_to:
            stmt = stmt.where(ReportRecord.created_at <= date_to)

        stmt = stmt.offset(offset).limit(limit)

        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_summary(r) for r in records]

    async def count_search_results(
        self,
        query: str | None = None,
        risk_filter: OverallRisk | None = None,
        flag_code: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        """Count search results matching the given criteria."""
        stmt = select(func.count(ReportRecord.report_id))

        if query:
            stmt = stmt.where(
                ReportRecord.character_name.ilike(f"%{query}%")
            )

        if risk_filter:
            stmt = stmt.where(ReportRecord.overall_risk == risk_filter.value)

        if flag_code:
            stmt = stmt.where(
                ReportRecord.flags_json.contains(f'"code": "{flag_code}"')
            )

        if date_from:
            stmt = stmt.where(ReportRecord.created_at >= date_from)
        if date_to:
            stmt = stmt.where(ReportRecord.created_at <= date_to)

        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def get_all_flag_codes(self) -> list[str]:
        """Get all unique flag codes from reports."""
        stmt = select(ReportRecord.flags_json).where(
            ReportRecord.flags_json.isnot(None)
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        flag_codes: set[str] = set()
        for (flags_json,) in rows:
            if flags_json:
                flags = json.loads(flags_json)
                for flag in flags:
                    code = flag.get("code")
                    if code:
                        flag_codes.add(code)

        return sorted(flag_codes)

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


class AnnotationRepository:
    """
    Async repository for report annotations.

    Handles CRUD operations for annotations attached to reports.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        report_id: UUID,
        author: str,
        content: str,
        annotation_type: str = "note",
    ) -> Annotation:
        """Create a new annotation on a report."""
        record = AnnotationRecord(
            report_id=str(report_id),
            author=author,
            content=content,
            annotation_type=annotation_type,
            created_at=datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def get_by_id(self, annotation_id: int) -> Annotation | None:
        """Get an annotation by ID."""
        stmt = select(AnnotationRecord).where(AnnotationRecord.id == annotation_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_model(record) if record else None

    async def get_by_report_id(self, report_id: UUID) -> list[Annotation]:
        """Get all annotations for a report, newest first."""
        stmt = (
            select(AnnotationRecord)
            .where(AnnotationRecord.report_id == str(report_id))
            .order_by(desc(AnnotationRecord.created_at))
        )
        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_model(r) for r in records]

    async def update(
        self,
        annotation_id: int,
        content: str | None = None,
        annotation_type: str | None = None,
    ) -> Annotation | None:
        """Update an annotation. Returns None if not found."""
        stmt = select(AnnotationRecord).where(AnnotationRecord.id == annotation_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return None

        if content is not None:
            record.content = content
        if annotation_type is not None:
            record.annotation_type = annotation_type
        record.updated_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def delete(self, annotation_id: int) -> bool:
        """Delete an annotation. Returns True if deleted."""
        stmt = select(AnnotationRecord).where(AnnotationRecord.id == annotation_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return False

        await self._session.delete(record)
        await self._session.commit()
        return True

    async def count_by_report_id(self, report_id: UUID) -> int:
        """Count annotations for a report."""
        stmt = select(func.count(AnnotationRecord.id)).where(
            AnnotationRecord.report_id == str(report_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    def _to_model(self, record: AnnotationRecord) -> Annotation:
        """Convert record to Pydantic model."""
        return Annotation(
            id=record.id,
            report_id=record.report_id,
            author=record.author,
            content=record.content,
            annotation_type=record.annotation_type,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
