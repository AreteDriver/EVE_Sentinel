"""Watchlist API endpoints for monitoring characters over time."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import WatchlistRepository, get_session_dependency
from backend.database.repository import WatchlistEntry
from backend.rate_limit import LIMITS, limiter

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


class AddToWatchlistRequest(BaseModel):
    """Request to add a character to the watchlist."""

    character_id: int
    character_name: str
    added_by: str
    reason: str | None = None
    priority: str = "normal"  # high, normal, low
    alert_on_change: bool = True
    alert_threshold: str = "any"  # any, yellow, red


class UpdateWatchlistRequest(BaseModel):
    """Request to update watchlist entry settings."""

    reason: str | None = None
    priority: str | None = None
    alert_on_change: bool | None = None
    alert_threshold: str | None = None


class WatchlistStats(BaseModel):
    """Watchlist statistics."""

    total: int
    high_priority: int
    normal_priority: int
    low_priority: int
    needing_reanalysis: int


@router.get("", response_model=list[WatchlistEntry])
@limiter.limit(LIMITS["reports"])
async def list_watchlist(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    priority: str | None = Query(default=None, description="Filter by priority"),
    session: AsyncSession = Depends(get_session_dependency),
) -> list[WatchlistEntry]:
    """
    List all characters on the watchlist.

    Supports filtering by priority (high, normal, low).
    """
    repo = WatchlistRepository(session)
    return await repo.list_all(limit=limit, offset=offset, priority=priority)


@router.get("/stats", response_model=WatchlistStats)
@limiter.limit(LIMITS["reports"])
async def get_watchlist_stats(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> WatchlistStats:
    """Get watchlist statistics."""
    repo = WatchlistRepository(session)

    total = await repo.count()
    high = await repo.count(priority="high")
    normal = await repo.count(priority="normal")
    low = await repo.count(priority="low")
    needing = await repo.list_needing_reanalysis()

    return WatchlistStats(
        total=total,
        high_priority=high,
        normal_priority=normal,
        low_priority=low,
        needing_reanalysis=len(needing),
    )


@router.get("/needing-reanalysis", response_model=list[WatchlistEntry])
@limiter.limit(LIMITS["reports"])
async def list_needing_reanalysis(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> list[WatchlistEntry]:
    """
    List characters that need reanalysis.

    Characters are flagged for reanalysis if they haven't been
    analyzed in the last 7 days.
    """
    repo = WatchlistRepository(session)
    return await repo.list_needing_reanalysis()


@router.get("/check/{character_id}")
@limiter.limit(LIMITS["reports"])
async def check_if_watched(
    request: Request,
    character_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> dict:
    """Check if a character is on the watchlist."""
    repo = WatchlistRepository(session)
    entry = await repo.get_by_character_id(character_id)

    return {
        "character_id": character_id,
        "is_watched": entry is not None,
        "watchlist_entry": entry,
    }


@router.get("/{watchlist_id}", response_model=WatchlistEntry)
@limiter.limit(LIMITS["reports"])
async def get_watchlist_entry(
    request: Request,
    watchlist_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> WatchlistEntry:
    """Get a specific watchlist entry."""
    repo = WatchlistRepository(session)
    entry = await repo.get_by_id(watchlist_id)

    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    return entry


@router.post("", response_model=WatchlistEntry, status_code=201)
@limiter.limit(LIMITS["reports"])
async def add_to_watchlist(
    request: Request,
    add_request: AddToWatchlistRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> WatchlistEntry:
    """
    Add a character to the watchlist.

    Priority levels:
    - high: Check frequently, important target
    - normal: Standard monitoring
    - low: Occasional check

    Alert thresholds:
    - any: Alert on any risk level change
    - yellow: Alert only when risk becomes YELLOW or RED
    - red: Alert only when risk becomes RED
    """
    repo = WatchlistRepository(session)

    # Check if already watched
    existing = await repo.get_by_character_id(add_request.character_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Character {add_request.character_id} is already on the watchlist",
        )

    # Validate priority
    valid_priorities = ["high", "normal", "low"]
    if add_request.priority not in valid_priorities:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority. Must be one of: {', '.join(valid_priorities)}",
        )

    # Validate alert threshold
    valid_thresholds = ["any", "yellow", "red"]
    if add_request.alert_threshold not in valid_thresholds:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid alert threshold. Must be one of: {', '.join(valid_thresholds)}",
        )

    return await repo.add(
        character_id=add_request.character_id,
        character_name=add_request.character_name,
        added_by=add_request.added_by,
        reason=add_request.reason,
        priority=add_request.priority,
        alert_on_change=add_request.alert_on_change,
        alert_threshold=add_request.alert_threshold,
    )


@router.patch("/{watchlist_id}", response_model=WatchlistEntry)
@limiter.limit(LIMITS["reports"])
async def update_watchlist_entry(
    request: Request,
    watchlist_id: int,
    update_request: UpdateWatchlistRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> WatchlistEntry:
    """Update watchlist entry settings."""
    repo = WatchlistRepository(session)

    # Validate priority if provided
    if update_request.priority:
        valid_priorities = ["high", "normal", "low"]
        if update_request.priority not in valid_priorities:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid priority. Must be one of: {', '.join(valid_priorities)}",
            )

    # Validate alert threshold if provided
    if update_request.alert_threshold:
        valid_thresholds = ["any", "yellow", "red"]
        if update_request.alert_threshold not in valid_thresholds:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid alert threshold. Must be one of: {', '.join(valid_thresholds)}",
            )

    updated = await repo.update(
        watchlist_id=watchlist_id,
        reason=update_request.reason,
        priority=update_request.priority,
        alert_on_change=update_request.alert_on_change,
        alert_threshold=update_request.alert_threshold,
    )

    if not updated:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    return updated


@router.delete("/{watchlist_id}", status_code=204)
@limiter.limit(LIMITS["reports"])
async def remove_from_watchlist(
    request: Request,
    watchlist_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> None:
    """Remove a character from the watchlist."""
    repo = WatchlistRepository(session)
    removed = await repo.remove(watchlist_id)

    if not removed:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")


@router.delete("/character/{character_id}", status_code=204)
@limiter.limit(LIMITS["reports"])
async def remove_character_from_watchlist(
    request: Request,
    character_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> None:
    """Remove a character from the watchlist by character ID."""
    repo = WatchlistRepository(session)
    removed = await repo.remove_by_character_id(character_id)

    if not removed:
        raise HTTPException(status_code=404, detail="Character not on watchlist")
