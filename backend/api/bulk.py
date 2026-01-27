"""Bulk operations API endpoints."""

import csv
import io
import zipfile
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import (
    ReportRepository,
    ReportTagRepository,
    get_session_dependency,
)
from backend.rate_limit import LIMITS, limiter
from backend.services import PDFGenerator

router = APIRouter(prefix="/api/v1/bulk", tags=["bulk"])


class BulkDeleteRequest(BaseModel):
    """Request for bulk report deletion."""

    report_ids: list[UUID]


class BulkTagRequest(BaseModel):
    """Request for bulk tagging."""

    report_ids: list[UUID]
    tag: str
    added_by: str = "admin"


class BulkExportRequest(BaseModel):
    """Request for bulk export."""

    report_ids: list[UUID]
    format: str = "csv"  # csv or pdf


class BulkActionResult(BaseModel):
    """Result of a bulk action."""

    success: bool
    processed: int
    failed: int
    message: str


@router.post("/delete", response_model=BulkActionResult)
@limiter.limit(LIMITS["admin"])
async def bulk_delete_reports(
    request: Request,
    delete_request: BulkDeleteRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> BulkActionResult:
    """
    Delete multiple reports at once.

    Requires admin access.
    Maximum 100 reports per request.
    """
    if not delete_request.report_ids:
        raise HTTPException(status_code=400, detail="No report IDs provided")

    if len(delete_request.report_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 reports per request")

    repo = ReportRepository(session)
    deleted = 0
    failed = 0

    for report_id in delete_request.report_ids:
        try:
            if await repo.delete_by_id(report_id):
                deleted += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    return BulkActionResult(
        success=failed == 0,
        processed=deleted,
        failed=failed,
        message=f"Deleted {deleted} reports, {failed} failed",
    )


@router.post("/tag", response_model=BulkActionResult)
@limiter.limit(LIMITS["admin"])
async def bulk_add_tag(
    request: Request,
    tag_request: BulkTagRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> BulkActionResult:
    """
    Add a tag to multiple reports.

    Maximum 100 reports per request.
    """
    if not tag_request.report_ids:
        raise HTTPException(status_code=400, detail="No report IDs provided")

    if len(tag_request.report_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 reports per request")

    if not tag_request.tag or len(tag_request.tag.strip()) == 0:
        raise HTTPException(status_code=400, detail="Tag cannot be empty")

    repo = ReportTagRepository(session)
    report_ids = [str(rid) for rid in tag_request.report_ids]

    added = await repo.bulk_add_tag(
        report_ids=report_ids,
        tag=tag_request.tag,
        added_by=tag_request.added_by,
    )

    return BulkActionResult(
        success=True,
        processed=added,
        failed=len(report_ids) - added,
        message=f"Tagged {added} reports with '{tag_request.tag}'",
    )


@router.post("/untag", response_model=BulkActionResult)
@limiter.limit(LIMITS["admin"])
async def bulk_remove_tag(
    request: Request,
    tag_request: BulkTagRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> BulkActionResult:
    """
    Remove a tag from multiple reports.

    Maximum 100 reports per request.
    """
    if not tag_request.report_ids:
        raise HTTPException(status_code=400, detail="No report IDs provided")

    if len(tag_request.report_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 reports per request")

    repo = ReportTagRepository(session)
    report_ids = [str(rid) for rid in tag_request.report_ids]

    removed = await repo.bulk_remove_tag(report_ids=report_ids, tag=tag_request.tag)

    return BulkActionResult(
        success=True,
        processed=removed,
        failed=len(report_ids) - removed,
        message=f"Removed tag '{tag_request.tag}' from {removed} reports",
    )


@router.get("/tags")
@limiter.limit(LIMITS["reports"])
async def get_all_tags(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> list[dict]:
    """Get all unique tags with usage counts."""
    repo = ReportTagRepository(session)
    return await repo.get_all_tags()


@router.get("/reports/{report_id}/tags")
@limiter.limit(LIMITS["reports"])
async def get_report_tags(
    request: Request,
    report_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> list[str]:
    """Get all tags for a specific report."""
    repo = ReportTagRepository(session)
    return await repo.get_tags_for_report(str(report_id))


@router.post("/reports/{report_id}/tags/{tag}")
@limiter.limit(LIMITS["reports"])
async def add_report_tag(
    request: Request,
    report_id: UUID,
    tag: str,
    session: AsyncSession = Depends(get_session_dependency),
) -> dict:
    """Add a tag to a report."""
    repo = ReportTagRepository(session)
    # TODO: Get added_by from session
    result = await repo.add_tag(str(report_id), tag, "admin")
    return {"success": True, "tag": result.tag}


@router.delete("/reports/{report_id}/tags/{tag}")
@limiter.limit(LIMITS["reports"])
async def remove_report_tag(
    request: Request,
    report_id: UUID,
    tag: str,
    session: AsyncSession = Depends(get_session_dependency),
) -> dict:
    """Remove a tag from a report."""
    repo = ReportTagRepository(session)
    removed = await repo.remove_tag(str(report_id), tag)

    if not removed:
        raise HTTPException(status_code=404, detail="Tag not found on report")

    return {"success": True}


@router.post("/export/csv")
@limiter.limit(LIMITS["bulk_pdf"])
async def bulk_export_csv(
    request: Request,
    export_request: BulkExportRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> Response:
    """
    Export multiple reports as CSV.

    Maximum 200 reports per request.
    """
    if not export_request.report_ids:
        raise HTTPException(status_code=400, detail="No report IDs provided")

    if len(export_request.report_ids) > 200:
        raise HTTPException(status_code=400, detail="Maximum 200 reports per request")

    repo = ReportRepository(session)
    reports = []

    for report_id in export_request.report_ids:
        report = await repo.get_by_id(report_id)
        if report:
            reports.append(report)

    if not reports:
        raise HTTPException(status_code=404, detail="No reports found")

    # Generate CSV
    output = io.StringIO()
    fieldnames = [
        "report_id",
        "character_id",
        "character_name",
        "overall_risk",
        "confidence",
        "red_flags",
        "yellow_flags",
        "green_flags",
        "created_at",
        "requested_by",
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for report in reports:
        writer.writerow(
            {
                "report_id": str(report.report_id),
                "character_id": report.character_id,
                "character_name": report.character_name,
                "overall_risk": report.overall_risk.value,
                "confidence": round(report.confidence * 100, 1),
                "red_flags": report.red_flag_count,
                "yellow_flags": report.yellow_flag_count,
                "green_flags": report.green_flag_count,
                "created_at": report.created_at.isoformat(),
                "requested_by": report.requested_by or "",
            }
        )

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"sentinel_bulk_export_{timestamp}.csv"

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/export/pdf")
@limiter.limit(LIMITS["bulk_pdf"])
async def bulk_export_pdf(
    request: Request,
    export_request: BulkExportRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> Response:
    """
    Export multiple reports as a ZIP file of PDFs.

    Maximum 50 reports per request.
    """
    if not export_request.report_ids:
        raise HTTPException(status_code=400, detail="No report IDs provided")

    if len(export_request.report_ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 reports per PDF export")

    repo = ReportRepository(session)
    pdf_generator = PDFGenerator()

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for report_id in export_request.report_ids:
            report = await repo.get_by_id(report_id)
            if report:
                pdf_content = pdf_generator.generate(report)
                filename = pdf_generator.generate_filename(report)
                zip_file.writestr(filename, pdf_content)

    zip_buffer.seek(0)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="sentinel_reports_{timestamp}.zip"',
        },
    )


@router.get("/reports/by-tag/{tag}")
@limiter.limit(LIMITS["reports"])
async def get_reports_by_tag(
    request: Request,
    tag: str,
    session: AsyncSession = Depends(get_session_dependency),
) -> list[str]:
    """Get all report IDs that have a specific tag."""
    repo = ReportTagRepository(session)
    return await repo.get_reports_by_tag(tag)
