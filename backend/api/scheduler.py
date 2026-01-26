"""Scheduler management API endpoints."""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import WatchlistRepository, get_session_dependency
from backend.rate_limit import LIMITS, limiter
from backend.services import scheduler

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


class SchedulerStatusResponse(BaseModel):
    """Response model for scheduler status."""

    enabled: bool
    running: bool
    interval_minutes: int
    max_per_run: int


class ReanalysisResultResponse(BaseModel):
    """Response model for reanalysis result."""

    analyzed: int
    success: int
    failed: int


class PendingReanalysisResponse(BaseModel):
    """Response model for pending reanalysis info."""

    count: int
    characters: list[dict]


@router.get("/status", response_model=SchedulerStatusResponse)
async def get_scheduler_status(request: Request) -> SchedulerStatusResponse:
    """Get current scheduler status."""
    return SchedulerStatusResponse(
        enabled=settings.scheduler_enabled,
        running=scheduler._running,
        interval_minutes=scheduler._interval_minutes,
        max_per_run=scheduler._max_analyses_per_run,
    )


@router.get("/pending", response_model=PendingReanalysisResponse)
@limiter.limit(LIMITS["reports"])
async def get_pending_reanalysis(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> PendingReanalysisResponse:
    """Get list of characters pending reanalysis."""
    repo = WatchlistRepository(session)
    characters = await repo.get_needing_reanalysis()

    return PendingReanalysisResponse(
        count=len(characters),
        characters=[
            {
                "character_id": c.character_id,
                "character_name": c.character_name,
                "priority": c.priority,
                "last_analysis_at": c.last_analysis_at.isoformat() if c.last_analysis_at else None,
                "last_risk_level": c.last_risk_level,
            }
            for c in characters
        ],
    )


@router.post("/run", response_model=ReanalysisResultResponse)
@limiter.limit(LIMITS["admin"])
async def trigger_reanalysis(
    request: Request,
    character_ids: list[int] | None = Query(
        default=None, description="Specific character IDs to reanalyze (omit for all pending)"
    ),
) -> ReanalysisResultResponse:
    """
    Manually trigger reanalysis.

    If character_ids is provided, only those characters are analyzed.
    Otherwise, all characters needing reanalysis are processed.
    """
    result = await scheduler.run_manual(character_ids)
    return ReanalysisResultResponse(
        analyzed=result["analyzed"],
        success=result["success"],
        failed=result["failed"],
    )


@router.post("/start", response_model=dict)
@limiter.limit(LIMITS["admin"])
async def start_scheduler(request: Request) -> dict:
    """Start the background scheduler."""
    if scheduler._running:
        return {"status": "already_running"}

    await scheduler.start()
    return {"status": "started"}


@router.post("/stop", response_model=dict)
@limiter.limit(LIMITS["admin"])
async def stop_scheduler(request: Request) -> dict:
    """Stop the background scheduler."""
    if not scheduler._running:
        return {"status": "not_running"}

    await scheduler.stop()
    return {"status": "stopped"}
