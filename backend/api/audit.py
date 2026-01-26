"""Audit logging API endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import AuditLog, AuditLogRepository, get_session_dependency
from backend.rate_limit import LIMITS, limiter

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


class AuditLogResponse(BaseModel):
    """Response model for audit log entry."""

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


class AuditStatsResponse(BaseModel):
    """Response model for audit statistics."""

    total_logs: int
    successful: int
    failed: int
    unique_users: int
    actions_breakdown: dict[str, int]
    recent_activity: list[AuditLogResponse]


def _to_response(log: AuditLog) -> AuditLogResponse:
    """Convert AuditLog to response model."""
    return AuditLogResponse(
        id=log.id,
        action=log.action,
        user_id=log.user_id,
        user_name=log.user_name,
        ip_address=log.ip_address,
        user_agent=log.user_agent,
        target_type=log.target_type,
        target_id=log.target_id,
        target_name=log.target_name,
        details=log.details,
        success=log.success,
        error_message=log.error_message,
        created_at=log.created_at,
    )


@router.get("", response_model=list[AuditLogResponse])
@limiter.limit(LIMITS["admin"])
async def list_audit_logs(
    request: Request,
    action: str | None = Query(default=None, description="Filter by action type"),
    user_id: str | None = Query(default=None, description="Filter by user ID"),
    target_type: str | None = Query(default=None, description="Filter by target type"),
    target_id: str | None = Query(default=None, description="Filter by target ID"),
    success: bool | None = Query(default=None, description="Filter by success status"),
    date_from: str | None = Query(default=None, description="Start date (ISO format)"),
    date_to: str | None = Query(default=None, description="End date (ISO format)"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=50, ge=1, le=200, description="Results per page"),
    session: AsyncSession = Depends(get_session_dependency),
) -> list[AuditLogResponse]:
    """
    List audit logs with filtering.

    Requires admin access in production.
    """
    offset = (page - 1) * limit

    # Parse date filters
    date_from_dt = None
    date_to_dt = None
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to)
        except ValueError:
            pass

    repo = AuditLogRepository(session)
    logs = await repo.list_logs(
        action=action,
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        success=success,
        date_from=date_from_dt,
        date_to=date_to_dt,
        limit=limit,
        offset=offset,
    )

    return [_to_response(log) for log in logs]


@router.get("/stats", response_model=AuditStatsResponse)
@limiter.limit(LIMITS["admin"])
async def get_audit_stats(
    request: Request,
    days: int = Query(default=30, ge=1, le=365, description="Days to analyze"),
    session: AsyncSession = Depends(get_session_dependency),
) -> AuditStatsResponse:
    """
    Get audit log statistics.

    Returns overview of audit activity for the specified period.
    """
    from datetime import UTC, timedelta

    repo = AuditLogRepository(session)
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Get counts
    total = await repo.count_logs(date_from=cutoff)
    successful = await repo.count_logs(date_from=cutoff, success=True)
    failed = await repo.count_logs(date_from=cutoff, success=False)

    # Get action breakdown
    actions_breakdown = {}
    for action in AuditLogRepository.ACTIONS:
        count = await repo.count_logs(action=action, date_from=cutoff)
        if count > 0:
            actions_breakdown[action] = count

    # Get recent activity
    recent_logs = await repo.list_logs(date_from=cutoff, limit=10)

    # Count unique users (simplified)
    all_logs = await repo.list_logs(date_from=cutoff, limit=10000)
    unique_users = len(set(log.user_id for log in all_logs if log.user_id))

    return AuditStatsResponse(
        total_logs=total,
        successful=successful,
        failed=failed,
        unique_users=unique_users,
        actions_breakdown=actions_breakdown,
        recent_activity=[_to_response(log) for log in recent_logs],
    )


@router.get("/user/{user_id}", response_model=list[AuditLogResponse])
@limiter.limit(LIMITS["admin"])
async def get_user_audit_logs(
    request: Request,
    user_id: str,
    days: int = Query(default=30, ge=1, le=365, description="Days to look back"),
    session: AsyncSession = Depends(get_session_dependency),
) -> list[AuditLogResponse]:
    """Get audit logs for a specific user."""
    repo = AuditLogRepository(session)
    logs = await repo.get_user_activity(user_id, days=days)
    return [_to_response(log) for log in logs]


@router.get("/target/{target_type}/{target_id}", response_model=list[AuditLogResponse])
@limiter.limit(LIMITS["admin"])
async def get_target_audit_logs(
    request: Request,
    target_type: str,
    target_id: str,
    session: AsyncSession = Depends(get_session_dependency),
) -> list[AuditLogResponse]:
    """Get audit logs for a specific target (report, character, etc.)."""
    repo = AuditLogRepository(session)
    logs = await repo.get_target_history(target_type, target_id)
    return [_to_response(log) for log in logs]


@router.get("/actions", response_model=list[str])
async def list_action_types(request: Request) -> list[str]:
    """List all available audit action types."""
    return AuditLogRepository.ACTIONS


@router.post("/cleanup", response_model=dict)
@limiter.limit(LIMITS["admin"])
async def cleanup_old_logs(
    request: Request,
    days: int = Query(default=365, ge=30, le=3650, description="Delete logs older than X days"),
    session: AsyncSession = Depends(get_session_dependency),
) -> dict:
    """
    Delete old audit logs.

    By default, removes logs older than 365 days.
    """
    repo = AuditLogRepository(session)
    deleted = await repo.cleanup_old_logs(days=days)
    return {"deleted_count": deleted}
