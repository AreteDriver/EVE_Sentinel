"""Repository for report persistence operations."""

import json
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
