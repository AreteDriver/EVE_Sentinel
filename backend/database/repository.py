"""Repository for report persistence operations."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import secrets

from backend.database.models import (
    AnnotationRecord,
    AuditLogRecord,
    ReportRecord,
    ShareRecord,
    UserRecord,
    WatchlistRecord,
)
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


class WatchlistEntry(BaseModel):
    """Pydantic model for watchlist entry."""

    id: int
    character_id: int
    character_name: str
    added_by: str
    reason: str | None = None
    priority: str = "normal"
    last_risk_level: str | None = None
    last_analysis_id: str | None = None
    last_analysis_at: datetime | None = None
    alert_on_change: bool = True
    alert_threshold: str = "any"
    created_at: datetime
    updated_at: datetime | None = None
    needs_reanalysis: bool = False  # Computed field


class Share(BaseModel):
    """Pydantic model for share link."""

    token: str
    report_id: str
    created_by: str
    note: str | None = None
    expires_at: datetime | None = None
    max_views: int | None = None
    view_count: int = 0
    is_active: bool = True
    created_at: datetime
    last_viewed_at: datetime | None = None
    is_expired: bool = False  # Computed field
    share_url: str | None = None  # Computed field


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
            stmt = stmt.where(ReportRecord.character_name.ilike(f"%{query}%"))

        # Risk level filter
        if risk_filter:
            stmt = stmt.where(ReportRecord.overall_risk == risk_filter.value)

        # Flag code filter (search in JSON)
        if flag_code:
            stmt = stmt.where(ReportRecord.flags_json.contains(f'"code": "{flag_code}"'))

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
            stmt = stmt.where(ReportRecord.character_name.ilike(f"%{query}%"))

        if risk_filter:
            stmt = stmt.where(ReportRecord.overall_risk == risk_filter.value)

        if flag_code:
            stmt = stmt.where(ReportRecord.flags_json.contains(f'"code": "{flag_code}"'))

        if date_from:
            stmt = stmt.where(ReportRecord.created_at >= date_from)
        if date_to:
            stmt = stmt.where(ReportRecord.created_at <= date_to)

        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def get_all_flag_codes(self) -> list[str]:
        """Get all unique flag codes from reports."""
        stmt = select(ReportRecord.flags_json).where(ReportRecord.flags_json.isnot(None))
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
        return [{"date": date, **counts} for date, counts in sorted(date_counts.items())]

    async def get_top_flags(self, limit: int = 10) -> list[dict]:
        """
        Get the most common flags across all reports.

        Returns a list of dicts with flag code and count.
        """
        # Get all reports with flags
        stmt = select(ReportRecord.flags_json).where(ReportRecord.flags_json.isnot(None))
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
        stmt = select(func.count(ReportRecord.report_id)).where(ReportRecord.created_at >= cutoff)
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


class WatchlistRepository:
    """
    Async repository for watchlist management.

    Handles tracking characters for monitoring over time.
    """

    # Consider a character needing reanalysis after 7 days
    REANALYSIS_THRESHOLD_DAYS = 7

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        character_id: int,
        character_name: str,
        added_by: str,
        reason: str | None = None,
        priority: str = "normal",
        alert_on_change: bool = True,
        alert_threshold: str = "any",
    ) -> WatchlistEntry:
        """Add a character to the watchlist."""
        record = WatchlistRecord(
            character_id=character_id,
            character_name=character_name,
            added_by=added_by,
            reason=reason,
            priority=priority,
            alert_on_change=alert_on_change,
            alert_threshold=alert_threshold,
            created_at=datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def get_by_id(self, watchlist_id: int) -> WatchlistEntry | None:
        """Get watchlist entry by ID."""
        stmt = select(WatchlistRecord).where(WatchlistRecord.id == watchlist_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_model(record) if record else None

    async def get_by_character_id(self, character_id: int) -> WatchlistEntry | None:
        """Get watchlist entry by character ID."""
        stmt = select(WatchlistRecord).where(WatchlistRecord.character_id == character_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_model(record) if record else None

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        priority: str | None = None,
    ) -> list[WatchlistEntry]:
        """List all watchlist entries."""
        stmt = select(WatchlistRecord).order_by(desc(WatchlistRecord.created_at))

        if priority:
            stmt = stmt.where(WatchlistRecord.priority == priority)

        stmt = stmt.offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_model(r) for r in records]

    async def list_needing_reanalysis(self) -> list[WatchlistEntry]:
        """List characters that need reanalysis (no analysis in threshold days)."""
        cutoff = datetime.now(UTC) - timedelta(days=self.REANALYSIS_THRESHOLD_DAYS)

        stmt = select(WatchlistRecord).where(
            (WatchlistRecord.last_analysis_at.is_(None))
            | (WatchlistRecord.last_analysis_at < cutoff)
        ).order_by(WatchlistRecord.priority.desc(), WatchlistRecord.last_analysis_at)

        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_model(r) for r in records]

    async def update(
        self,
        watchlist_id: int,
        reason: str | None = None,
        priority: str | None = None,
        alert_on_change: bool | None = None,
        alert_threshold: str | None = None,
    ) -> WatchlistEntry | None:
        """Update watchlist entry settings."""
        stmt = select(WatchlistRecord).where(WatchlistRecord.id == watchlist_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return None

        if reason is not None:
            record.reason = reason
        if priority is not None:
            record.priority = priority
        if alert_on_change is not None:
            record.alert_on_change = alert_on_change
        if alert_threshold is not None:
            record.alert_threshold = alert_threshold
        record.updated_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def update_analysis(
        self,
        character_id: int,
        report_id: UUID,
        risk_level: str,
    ) -> WatchlistEntry | None:
        """Update the last analysis info for a watchlist entry."""
        stmt = select(WatchlistRecord).where(WatchlistRecord.character_id == character_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return None

        record.last_analysis_id = str(report_id)
        record.last_risk_level = risk_level
        record.last_analysis_at = datetime.now(UTC)
        record.updated_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def remove(self, watchlist_id: int) -> bool:
        """Remove a character from the watchlist."""
        stmt = select(WatchlistRecord).where(WatchlistRecord.id == watchlist_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return False

        await self._session.delete(record)
        await self._session.commit()
        return True

    async def remove_by_character_id(self, character_id: int) -> bool:
        """Remove a character from the watchlist by character ID."""
        stmt = select(WatchlistRecord).where(WatchlistRecord.character_id == character_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return False

        await self._session.delete(record)
        await self._session.commit()
        return True

    async def count(self, priority: str | None = None) -> int:
        """Count watchlist entries."""
        stmt = select(func.count(WatchlistRecord.id))
        if priority:
            stmt = stmt.where(WatchlistRecord.priority == priority)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def is_watched(self, character_id: int) -> bool:
        """Check if a character is on the watchlist."""
        entry = await self.get_by_character_id(character_id)
        return entry is not None

    def _to_model(self, record: WatchlistRecord) -> WatchlistEntry:
        """Convert record to Pydantic model."""
        # Calculate if reanalysis needed
        needs_reanalysis = False
        if record.last_analysis_at is None:
            needs_reanalysis = True
        else:
            cutoff = datetime.now(UTC) - timedelta(days=self.REANALYSIS_THRESHOLD_DAYS)
            needs_reanalysis = record.last_analysis_at < cutoff

        return WatchlistEntry(
            id=record.id,
            character_id=record.character_id,
            character_name=record.character_name,
            added_by=record.added_by,
            reason=record.reason,
            priority=record.priority,
            last_risk_level=record.last_risk_level,
            last_analysis_id=record.last_analysis_id,
            last_analysis_at=record.last_analysis_at,
            alert_on_change=bool(record.alert_on_change),
            alert_threshold=record.alert_threshold,
            created_at=record.created_at,
            updated_at=record.updated_at,
            needs_reanalysis=needs_reanalysis,
        )


class ShareRepository:
    """
    Async repository for report sharing.

    Handles creating and managing shareable links for reports.
    """

    def __init__(self, session: AsyncSession, base_url: str = "") -> None:
        self._session = session
        self._base_url = base_url

    def _generate_token(self) -> str:
        """Generate a secure random token."""
        return secrets.token_urlsafe(32)

    async def create(
        self,
        report_id: UUID,
        created_by: str,
        note: str | None = None,
        expires_in_days: int | None = None,
        max_views: int | None = None,
    ) -> Share:
        """Create a new share link for a report."""
        token = self._generate_token()

        expires_at = None
        if expires_in_days:
            expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)

        record = ShareRecord(
            token=token,
            report_id=str(report_id),
            created_by=created_by,
            note=note,
            expires_at=expires_at,
            max_views=max_views,
            view_count=0,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def get_by_token(self, token: str) -> Share | None:
        """Get a share by token."""
        stmt = select(ShareRecord).where(ShareRecord.token == token)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_model(record) if record else None

    async def get_by_report_id(self, report_id: UUID) -> list[Share]:
        """Get all shares for a report."""
        stmt = (
            select(ShareRecord)
            .where(ShareRecord.report_id == str(report_id))
            .order_by(desc(ShareRecord.created_at))
        )
        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_model(r) for r in records]

    async def record_view(self, token: str) -> Share | None:
        """Record a view on a share link. Returns None if share is invalid."""
        stmt = select(ShareRecord).where(ShareRecord.token == token)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return None

        # Check if still valid
        if not record.is_active:
            return None

        if record.expires_at and datetime.now(UTC) > record.expires_at:
            return None

        if record.max_views and record.view_count >= record.max_views:
            return None

        # Increment view count
        record.view_count += 1
        record.last_viewed_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def revoke(self, token: str) -> bool:
        """Revoke a share link."""
        stmt = select(ShareRecord).where(ShareRecord.token == token)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return False

        record.is_active = False
        await self._session.commit()
        return True

    async def delete(self, token: str) -> bool:
        """Delete a share link."""
        stmt = select(ShareRecord).where(ShareRecord.token == token)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return False

        await self._session.delete(record)
        await self._session.commit()
        return True

    async def list_active(self, limit: int = 100) -> list[Share]:
        """List all active share links."""
        stmt = (
            select(ShareRecord)
            .where(ShareRecord.is_active == True)  # noqa: E712
            .order_by(desc(ShareRecord.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_model(r) for r in records]

    async def cleanup_expired(self) -> int:
        """Deactivate expired shares. Returns count of deactivated shares."""
        now = datetime.now(UTC)
        stmt = select(ShareRecord).where(
            (ShareRecord.is_active == True)  # noqa: E712
            & (
                (ShareRecord.expires_at.isnot(None) & (ShareRecord.expires_at < now))
                | (
                    ShareRecord.max_views.isnot(None)
                    & (ShareRecord.view_count >= ShareRecord.max_views)
                )
            )
        )
        result = await self._session.execute(stmt)
        records = result.scalars().all()

        for record in records:
            record.is_active = False

        await self._session.commit()
        return len(records)

    def _to_model(self, record: ShareRecord) -> Share:
        """Convert record to Pydantic model."""
        now = datetime.now(UTC)

        # Calculate if expired
        is_expired = False
        if not record.is_active:
            is_expired = True
        elif record.expires_at and now > record.expires_at:
            is_expired = True
        elif record.max_views and record.view_count >= record.max_views:
            is_expired = True

        # Build share URL
        share_url = f"{self._base_url}/share/{record.token}" if self._base_url else None

        return Share(
            token=record.token,
            report_id=record.report_id,
            created_by=record.created_by,
            note=record.note,
            expires_at=record.expires_at,
            max_views=record.max_views,
            view_count=record.view_count,
            is_active=bool(record.is_active),
            created_at=record.created_at,
            last_viewed_at=record.last_viewed_at,
            is_expired=is_expired,
            share_url=share_url,
        )


class AuditLog(BaseModel):
    """Pydantic model for audit log entry."""

    id: int
    action: str
    user_id: str | None = None
    user_name: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    target_name: str | None = None
    details: dict | None = None
    success: bool = True
    error_message: str | None = None
    created_at: datetime


class User(BaseModel):
    """Pydantic model for user account."""

    character_id: int
    character_name: str
    role: str = "viewer"
    is_active: bool = True
    corporation_id: int | None = None
    alliance_id: int | None = None
    email: str | None = None
    email_on_watchlist_change: bool = True
    email_on_red_alert: bool = True
    email_on_yellow_alert: bool = False
    created_at: datetime
    last_login_at: datetime | None = None
    updated_at: datetime | None = None


class AuditLogRepository:
    """
    Async repository for audit logging.

    Records user actions for security and compliance.
    """

    # Available actions
    ACTIONS = [
        "analyze",
        "view_report",
        "delete_report",
        "create_share",
        "revoke_share",
        "view_shared",
        "add_watchlist",
        "remove_watchlist",
        "update_watchlist",
        "add_annotation",
        "delete_annotation",
        "login",
        "logout",
        "user_create",
        "user_update",
        "user_delete",
        "batch_analyze",
        "export_csv",
        "export_pdf",
    ]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        action: str,
        user_id: str | None = None,
        user_name: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        target_name: str | None = None,
        details: dict | None = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> AuditLog:
        """Create an audit log entry."""
        record = AuditLogRecord(
            action=action,
            user_id=user_id,
            user_name=user_name,
            ip_address=ip_address,
            user_agent=user_agent,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            details_json=json.dumps(details) if details else None,
            success=success,
            error_message=error_message,
            created_at=datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def get_by_id(self, log_id: int) -> AuditLog | None:
        """Get an audit log entry by ID."""
        stmt = select(AuditLogRecord).where(AuditLogRecord.id == log_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_model(record) if record else None

    async def list_logs(
        self,
        action: str | None = None,
        user_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        success: bool | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        """List audit logs with filtering."""
        stmt = select(AuditLogRecord).order_by(desc(AuditLogRecord.created_at))

        if action:
            stmt = stmt.where(AuditLogRecord.action == action)
        if user_id:
            stmt = stmt.where(AuditLogRecord.user_id == user_id)
        if target_type:
            stmt = stmt.where(AuditLogRecord.target_type == target_type)
        if target_id:
            stmt = stmt.where(AuditLogRecord.target_id == target_id)
        if success is not None:
            stmt = stmt.where(AuditLogRecord.success == success)
        if date_from:
            stmt = stmt.where(AuditLogRecord.created_at >= date_from)
        if date_to:
            stmt = stmt.where(AuditLogRecord.created_at <= date_to)

        stmt = stmt.offset(offset).limit(limit)

        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_model(r) for r in records]

    async def count_logs(
        self,
        action: str | None = None,
        user_id: str | None = None,
        target_type: str | None = None,
        success: bool | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        """Count audit logs matching filters."""
        stmt = select(func.count(AuditLogRecord.id))

        if action:
            stmt = stmt.where(AuditLogRecord.action == action)
        if user_id:
            stmt = stmt.where(AuditLogRecord.user_id == user_id)
        if target_type:
            stmt = stmt.where(AuditLogRecord.target_type == target_type)
        if success is not None:
            stmt = stmt.where(AuditLogRecord.success == success)
        if date_from:
            stmt = stmt.where(AuditLogRecord.created_at >= date_from)
        if date_to:
            stmt = stmt.where(AuditLogRecord.created_at <= date_to)

        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def get_user_activity(
        self,
        user_id: str,
        days: int = 30,
    ) -> list[AuditLog]:
        """Get recent activity for a specific user."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return await self.list_logs(
            user_id=user_id,
            date_from=cutoff,
            limit=500,
        )

    async def get_target_history(
        self,
        target_type: str,
        target_id: str,
    ) -> list[AuditLog]:
        """Get all actions on a specific target."""
        return await self.list_logs(
            target_type=target_type,
            target_id=target_id,
            limit=500,
        )

    async def cleanup_old_logs(self, days: int = 365) -> int:
        """Delete audit logs older than specified days."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = select(AuditLogRecord).where(AuditLogRecord.created_at < cutoff)
        result = await self._session.execute(stmt)
        records = result.scalars().all()

        for record in records:
            await self._session.delete(record)

        await self._session.commit()
        return len(records)

    def _to_model(self, record: AuditLogRecord) -> AuditLog:
        """Convert record to Pydantic model."""
        return AuditLog(
            id=record.id,
            action=record.action,
            user_id=record.user_id,
            user_name=record.user_name,
            ip_address=record.ip_address,
            user_agent=record.user_agent,
            target_type=record.target_type,
            target_id=record.target_id,
            target_name=record.target_name,
            details=json.loads(record.details_json) if record.details_json else None,
            success=bool(record.success),
            error_message=record.error_message,
            created_at=record.created_at,
        )


class UserRepository:
    """
    Async repository for user management.

    Handles user accounts and role-based access control.
    """

    ROLES = ["admin", "recruiter", "viewer"]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        character_id: int,
        character_name: str,
        role: str = "viewer",
        corporation_id: int | None = None,
        alliance_id: int | None = None,
    ) -> User:
        """Create a new user account."""
        if role not in self.ROLES:
            raise ValueError(f"Invalid role: {role}. Must be one of {self.ROLES}")

        record = UserRecord(
            character_id=character_id,
            character_name=character_name,
            role=role,
            is_active=True,
            corporation_id=corporation_id,
            alliance_id=alliance_id,
            created_at=datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def get_by_id(self, character_id: int) -> User | None:
        """Get a user by character ID."""
        stmt = select(UserRecord).where(UserRecord.character_id == character_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_model(record) if record else None

    async def get_or_create(
        self,
        character_id: int,
        character_name: str,
        corporation_id: int | None = None,
        alliance_id: int | None = None,
    ) -> tuple[User, bool]:
        """Get existing user or create new one. Returns (user, created)."""
        user = await self.get_by_id(character_id)
        if user:
            return user, False

        user = await self.create(
            character_id=character_id,
            character_name=character_name,
            corporation_id=corporation_id,
            alliance_id=alliance_id,
        )
        return user, True

    async def list_users(
        self,
        role: str | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[User]:
        """List users with optional filtering."""
        stmt = select(UserRecord).order_by(UserRecord.character_name)

        if role:
            stmt = stmt.where(UserRecord.role == role)
        if is_active is not None:
            stmt = stmt.where(UserRecord.is_active == is_active)

        stmt = stmt.offset(offset).limit(limit)

        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_model(r) for r in records]

    async def count_users(
        self,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> int:
        """Count users matching filters."""
        stmt = select(func.count(UserRecord.character_id))

        if role:
            stmt = stmt.where(UserRecord.role == role)
        if is_active is not None:
            stmt = stmt.where(UserRecord.is_active == is_active)

        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def update_role(self, character_id: int, role: str) -> User | None:
        """Update a user's role."""
        if role not in self.ROLES:
            raise ValueError(f"Invalid role: {role}. Must be one of {self.ROLES}")

        stmt = select(UserRecord).where(UserRecord.character_id == character_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return None

        record.role = role
        record.updated_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def update_status(self, character_id: int, is_active: bool) -> User | None:
        """Activate or deactivate a user."""
        stmt = select(UserRecord).where(UserRecord.character_id == character_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return None

        record.is_active = is_active
        record.updated_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def record_login(self, character_id: int) -> User | None:
        """Record a user login."""
        stmt = select(UserRecord).where(UserRecord.character_id == character_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return None

        record.last_login_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def delete(self, character_id: int) -> bool:
        """Delete a user account."""
        stmt = select(UserRecord).where(UserRecord.character_id == character_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return False

        await self._session.delete(record)
        await self._session.commit()
        return True

    async def get_users_for_email_alert(
        self,
        alert_type: str = "watchlist_change",
        risk_level: str | None = None,
    ) -> list[User]:
        """
        Get users who should receive email alerts.

        Args:
            alert_type: Type of alert (watchlist_change, new_analysis)
            risk_level: Risk level triggering the alert (RED, YELLOW)

        Returns:
            List of users with email configured for this alert type
        """
        stmt = select(UserRecord).where(
            UserRecord.is_active == True,
            UserRecord.email.isnot(None),
        )

        if alert_type == "watchlist_change":
            stmt = stmt.where(UserRecord.email_on_watchlist_change == True)

        # Filter by risk level preference
        if risk_level == "RED":
            stmt = stmt.where(UserRecord.email_on_red_alert == True)
        elif risk_level == "YELLOW":
            stmt = stmt.where(UserRecord.email_on_yellow_alert == True)

        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_model(r) for r in records]

    async def update_email_preferences(
        self,
        character_id: int,
        email: str | None = None,
        email_on_watchlist_change: bool | None = None,
        email_on_red_alert: bool | None = None,
        email_on_yellow_alert: bool | None = None,
    ) -> User | None:
        """Update a user's email notification preferences."""
        stmt = select(UserRecord).where(UserRecord.character_id == character_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return None

        if email is not None:
            record.email = email
        if email_on_watchlist_change is not None:
            record.email_on_watchlist_change = email_on_watchlist_change
        if email_on_red_alert is not None:
            record.email_on_red_alert = email_on_red_alert
        if email_on_yellow_alert is not None:
            record.email_on_yellow_alert = email_on_yellow_alert

        record.updated_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    def _to_model(self, record: UserRecord) -> User:
        """Convert record to Pydantic model."""
        return User(
            character_id=record.character_id,
            character_name=record.character_name,
            role=record.role,
            is_active=bool(record.is_active),
            corporation_id=record.corporation_id,
            alliance_id=record.alliance_id,
            email=record.email,
            email_on_watchlist_change=bool(record.email_on_watchlist_change),
            email_on_red_alert=bool(record.email_on_red_alert),
            email_on_yellow_alert=bool(record.email_on_yellow_alert),
            created_at=record.created_at,
            last_login_at=record.last_login_at,
            updated_at=record.updated_at,
        )


class FlagRule(BaseModel):
    """Pydantic model for custom flag rule."""

    id: int
    name: str
    description: str | None = None
    code: str
    severity: str  # RED, YELLOW, GREEN
    condition_type: str
    condition_params: dict
    flag_message: str
    is_active: bool = True
    priority: int = 100
    created_by: str
    created_at: datetime
    updated_at: datetime | None = None


class FlagRuleRepository:
    """
    Async repository for custom flag rules.

    Manages user-defined flag rules for custom risk detection.
    """

    # Available condition types
    CONDITION_TYPES = [
        "corp_member",       # Character is member of specific corp
        "alliance_member",   # Character is member of specific alliance
        "corp_history",      # Character was ever in specific corp
        "character_age",     # Character age (days) comparison
        "security_status",   # Security status comparison
        "kill_count",        # Kill count comparison
        "death_count",       # Death count comparison
        "zkill_danger",      # zKillboard danger ratio comparison
    ]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        name: str,
        code: str,
        severity: str,
        condition_type: str,
        condition_params: dict,
        flag_message: str,
        created_by: str,
        description: str | None = None,
        priority: int = 100,
    ) -> FlagRule:
        """Create a new flag rule."""
        from backend.database.models import FlagRuleRecord

        record = FlagRuleRecord(
            name=name,
            description=description,
            code=code.upper(),
            severity=severity.upper(),
            condition_type=condition_type,
            condition_params_json=json.dumps(condition_params),
            flag_message=flag_message,
            is_active=True,
            priority=priority,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def get_by_id(self, rule_id: int) -> FlagRule | None:
        """Get a rule by ID."""
        from backend.database.models import FlagRuleRecord

        stmt = select(FlagRuleRecord).where(FlagRuleRecord.id == rule_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_model(record) if record else None

    async def get_by_code(self, code: str) -> FlagRule | None:
        """Get a rule by code."""
        from backend.database.models import FlagRuleRecord

        stmt = select(FlagRuleRecord).where(FlagRuleRecord.code == code.upper())
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_model(record) if record else None

    async def list_rules(
        self,
        active_only: bool = False,
        severity: str | None = None,
    ) -> list[FlagRule]:
        """List all flag rules."""
        from backend.database.models import FlagRuleRecord

        stmt = select(FlagRuleRecord).order_by(FlagRuleRecord.priority)

        if active_only:
            stmt = stmt.where(FlagRuleRecord.is_active == True)
        if severity:
            stmt = stmt.where(FlagRuleRecord.severity == severity.upper())

        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_model(r) for r in records]

    async def get_active_rules(self) -> list[FlagRule]:
        """Get all active rules sorted by priority."""
        return await self.list_rules(active_only=True)

    async def update(
        self,
        rule_id: int,
        name: str | None = None,
        description: str | None = None,
        severity: str | None = None,
        condition_type: str | None = None,
        condition_params: dict | None = None,
        flag_message: str | None = None,
        is_active: bool | None = None,
        priority: int | None = None,
    ) -> FlagRule | None:
        """Update a flag rule."""
        from backend.database.models import FlagRuleRecord

        stmt = select(FlagRuleRecord).where(FlagRuleRecord.id == rule_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return None

        if name is not None:
            record.name = name
        if description is not None:
            record.description = description
        if severity is not None:
            record.severity = severity.upper()
        if condition_type is not None:
            record.condition_type = condition_type
        if condition_params is not None:
            record.condition_params_json = json.dumps(condition_params)
        if flag_message is not None:
            record.flag_message = flag_message
        if is_active is not None:
            record.is_active = is_active
        if priority is not None:
            record.priority = priority

        record.updated_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def delete(self, rule_id: int) -> bool:
        """Delete a flag rule."""
        from backend.database.models import FlagRuleRecord

        stmt = select(FlagRuleRecord).where(FlagRuleRecord.id == rule_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return False

        await self._session.delete(record)
        await self._session.commit()
        return True

    def _to_model(self, record) -> FlagRule:
        """Convert record to Pydantic model."""
        return FlagRule(
            id=record.id,
            name=record.name,
            description=record.description,
            code=record.code,
            severity=record.severity,
            condition_type=record.condition_type,
            condition_params=json.loads(record.condition_params_json),
            flag_message=record.flag_message,
            is_active=bool(record.is_active),
            priority=record.priority,
            created_by=record.created_by,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class ReportTag(BaseModel):
    """Pydantic model for report tag."""

    id: int
    report_id: str
    tag: str
    added_by: str
    created_at: datetime


class ReportTagRepository:
    """
    Async repository for report tags.

    Manages tags applied to reports for organization and bulk operations.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_tag(self, report_id: str, tag: str, added_by: str) -> ReportTag:
        """Add a tag to a report."""
        from backend.database.models import ReportTagRecord

        record = ReportTagRecord(
            report_id=report_id,
            tag=tag.lower().strip(),
            added_by=added_by,
            created_at=datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return self._to_model(record)

    async def remove_tag(self, report_id: str, tag: str) -> bool:
        """Remove a tag from a report."""
        from backend.database.models import ReportTagRecord

        stmt = select(ReportTagRecord).where(
            ReportTagRecord.report_id == report_id,
            ReportTagRecord.tag == tag.lower().strip(),
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return False

        await self._session.delete(record)
        await self._session.commit()
        return True

    async def get_tags_for_report(self, report_id: str) -> list[str]:
        """Get all tags for a report."""
        from backend.database.models import ReportTagRecord

        stmt = select(ReportTagRecord).where(ReportTagRecord.report_id == report_id)
        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [r.tag for r in records]

    async def get_reports_by_tag(self, tag: str) -> list[str]:
        """Get all report IDs with a specific tag."""
        from backend.database.models import ReportTagRecord

        stmt = select(ReportTagRecord.report_id).where(
            ReportTagRecord.tag == tag.lower().strip()
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_tags(self) -> list[dict]:
        """Get all unique tags with counts."""
        from backend.database.models import ReportTagRecord

        stmt = (
            select(ReportTagRecord.tag, func.count(ReportTagRecord.id).label("count"))
            .group_by(ReportTagRecord.tag)
            .order_by(desc("count"))
        )
        result = await self._session.execute(stmt)
        return [{"tag": row.tag, "count": row.count} for row in result.all()]

    async def bulk_add_tag(
        self, report_ids: list[str], tag: str, added_by: str
    ) -> int:
        """Add a tag to multiple reports. Returns count of successful adds."""
        from backend.database.models import ReportTagRecord

        added = 0
        tag = tag.lower().strip()

        for report_id in report_ids:
            # Check if tag already exists
            existing = await self.get_tags_for_report(report_id)
            if tag in existing:
                continue

            try:
                record = ReportTagRecord(
                    report_id=report_id,
                    tag=tag,
                    added_by=added_by,
                    created_at=datetime.now(UTC),
                )
                self._session.add(record)
                added += 1
            except Exception:
                continue

        await self._session.commit()
        return added

    async def bulk_remove_tag(self, report_ids: list[str], tag: str) -> int:
        """Remove a tag from multiple reports. Returns count of successful removes."""
        from backend.database.models import ReportTagRecord

        tag = tag.lower().strip()
        removed = 0

        for report_id in report_ids:
            stmt = select(ReportTagRecord).where(
                ReportTagRecord.report_id == report_id,
                ReportTagRecord.tag == tag,
            )
            result = await self._session.execute(stmt)
            record = result.scalar_one_or_none()

            if record:
                await self._session.delete(record)
                removed += 1

        await self._session.commit()
        return removed

    def _to_model(self, record) -> ReportTag:
        """Convert record to Pydantic model."""
        return ReportTag(
            id=record.id,
            report_id=record.report_id,
            tag=record.tag,
            added_by=record.added_by,
            created_at=record.created_at,
        )
