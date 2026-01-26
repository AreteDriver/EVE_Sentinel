"""Report sharing API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import ReportRepository, ShareRepository, get_session_dependency
from backend.database.repository import Share
from backend.rate_limit import LIMITS, limiter

router = APIRouter(prefix="/api/v1/shares", tags=["shares"])


class CreateShareRequest(BaseModel):
    """Request to create a share link."""

    report_id: UUID
    created_by: str
    note: str | None = None
    expires_in_days: int | None = None  # None = never expires
    max_views: int | None = None  # None = unlimited views


class ShareResponse(BaseModel):
    """Response with share details."""

    token: str
    report_id: str
    share_url: str
    created_by: str
    note: str | None = None
    expires_at: str | None = None
    max_views: int | None = None
    view_count: int
    is_active: bool
    is_expired: bool


@router.post("", response_model=ShareResponse, status_code=201)
@limiter.limit(LIMITS["reports"])
async def create_share(
    request: Request,
    share_request: CreateShareRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> ShareResponse:
    """
    Create a shareable link for a report.

    Options:
    - expires_in_days: Number of days until link expires (None = never)
    - max_views: Maximum number of views allowed (None = unlimited)
    """
    # Verify report exists
    report_repo = ReportRepository(session)
    report = await report_repo.get_by_id(share_request.report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # Get base URL from request
    base_url = str(request.base_url).rstrip("/")

    share_repo = ShareRepository(session, base_url=base_url)
    share = await share_repo.create(
        report_id=share_request.report_id,
        created_by=share_request.created_by,
        note=share_request.note,
        expires_in_days=share_request.expires_in_days,
        max_views=share_request.max_views,
    )

    return _to_response(share, base_url)


@router.get("/{token}", response_model=ShareResponse)
@limiter.limit(LIMITS["reports"])
async def get_share(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session_dependency),
) -> ShareResponse:
    """Get share link details by token."""
    base_url = str(request.base_url).rstrip("/")
    share_repo = ShareRepository(session, base_url=base_url)
    share = await share_repo.get_by_token(token)

    if not share:
        raise HTTPException(status_code=404, detail="Share not found")

    return _to_response(share, base_url)


@router.get("/report/{report_id}", response_model=list[ShareResponse])
@limiter.limit(LIMITS["reports"])
async def list_report_shares(
    request: Request,
    report_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> list[ShareResponse]:
    """List all share links for a report."""
    base_url = str(request.base_url).rstrip("/")
    share_repo = ShareRepository(session, base_url=base_url)
    shares = await share_repo.get_by_report_id(report_id)

    return [_to_response(s, base_url) for s in shares]


@router.delete("/{token}", status_code=204)
@limiter.limit(LIMITS["reports"])
async def revoke_share(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session_dependency),
) -> None:
    """Revoke a share link (makes it inactive but keeps record)."""
    share_repo = ShareRepository(session)
    revoked = await share_repo.revoke(token)

    if not revoked:
        raise HTTPException(status_code=404, detail="Share not found")


@router.delete("/{token}/permanent", status_code=204)
@limiter.limit(LIMITS["reports"])
async def delete_share(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session_dependency),
) -> None:
    """Permanently delete a share link."""
    share_repo = ShareRepository(session)
    deleted = await share_repo.delete(token)

    if not deleted:
        raise HTTPException(status_code=404, detail="Share not found")


@router.get("", response_model=list[ShareResponse])
@limiter.limit(LIMITS["reports"])
async def list_active_shares(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session_dependency),
) -> list[ShareResponse]:
    """List all active share links."""
    base_url = str(request.base_url).rstrip("/")
    share_repo = ShareRepository(session, base_url=base_url)
    shares = await share_repo.list_active(limit=limit)

    return [_to_response(s, base_url) for s in shares]


@router.post("/cleanup", response_model=dict)
@limiter.limit(LIMITS["admin"])
async def cleanup_expired_shares(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> dict:
    """Deactivate all expired share links."""
    share_repo = ShareRepository(session)
    count = await share_repo.cleanup_expired()

    return {"deactivated_count": count}


def _to_response(share: Share, base_url: str) -> ShareResponse:
    """Convert Share model to response."""
    return ShareResponse(
        token=share.token,
        report_id=share.report_id,
        share_url=f"{base_url}/share/{share.token}",
        created_by=share.created_by,
        note=share.note,
        expires_at=share.expires_at.isoformat() if share.expires_at else None,
        max_views=share.max_views,
        view_count=share.view_count,
        is_active=share.is_active,
        is_expired=share.is_expired,
    )
