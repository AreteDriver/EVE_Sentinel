"""Analytics API endpoints."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import (
    AuditLogRecord,
    ReportRecord,
    WatchlistRecord,
    get_session_dependency,
)
from backend.rate_limit import LIMITS, limiter

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


class OverviewStats(BaseModel):
    """Overall statistics."""

    total_reports: int
    total_characters_analyzed: int
    total_watchlist: int
    reports_today: int
    reports_this_week: int
    reports_this_month: int


class RiskDistribution(BaseModel):
    """Risk level distribution."""

    red: int
    yellow: int
    green: int
    red_percent: float
    yellow_percent: float
    green_percent: float


class TimeSeriesPoint(BaseModel):
    """Single point in time series data."""

    date: str
    count: int
    red: int = 0
    yellow: int = 0
    green: int = 0


class RecruiterActivity(BaseModel):
    """Activity stats for a recruiter."""

    recruiter: str
    total_analyses: int
    last_active: str | None


class TopFlag(BaseModel):
    """Most common flag."""

    code: str
    title: str
    count: int
    severity: str


class AnalyticsDashboard(BaseModel):
    """Full analytics dashboard data."""

    overview: OverviewStats
    risk_distribution: RiskDistribution
    reports_over_time: list[TimeSeriesPoint]
    top_recruiters: list[RecruiterActivity]
    top_red_flags: list[TopFlag]
    top_yellow_flags: list[TopFlag]


@router.get("/overview", response_model=OverviewStats)
@limiter.limit(LIMITS["reports"])
async def get_overview_stats(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> OverviewStats:
    """Get overview statistics."""
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = today_start.replace(day=1)

    # Total reports
    total_stmt = select(func.count(ReportRecord.report_id))
    total_result = await session.execute(total_stmt)
    total_reports = total_result.scalar() or 0

    # Unique characters
    unique_stmt = select(func.count(func.distinct(ReportRecord.character_id)))
    unique_result = await session.execute(unique_stmt)
    total_characters = unique_result.scalar() or 0

    # Watchlist count
    watchlist_stmt = select(func.count(WatchlistRecord.id))
    watchlist_result = await session.execute(watchlist_stmt)
    total_watchlist = watchlist_result.scalar() or 0

    # Reports today
    today_stmt = select(func.count(ReportRecord.report_id)).where(
        ReportRecord.created_at >= today_start
    )
    today_result = await session.execute(today_stmt)
    reports_today = today_result.scalar() or 0

    # Reports this week
    week_stmt = select(func.count(ReportRecord.report_id)).where(
        ReportRecord.created_at >= week_start
    )
    week_result = await session.execute(week_stmt)
    reports_week = week_result.scalar() or 0

    # Reports this month
    month_stmt = select(func.count(ReportRecord.report_id)).where(
        ReportRecord.created_at >= month_start
    )
    month_result = await session.execute(month_stmt)
    reports_month = month_result.scalar() or 0

    return OverviewStats(
        total_reports=total_reports,
        total_characters_analyzed=total_characters,
        total_watchlist=total_watchlist,
        reports_today=reports_today,
        reports_this_week=reports_week,
        reports_this_month=reports_month,
    )


@router.get("/risk-distribution", response_model=RiskDistribution)
@limiter.limit(LIMITS["reports"])
async def get_risk_distribution(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session_dependency),
) -> RiskDistribution:
    """Get risk level distribution for a time period."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Count by risk level
    red_stmt = select(func.count(ReportRecord.report_id)).where(
        ReportRecord.created_at >= cutoff,
        ReportRecord.overall_risk == "RED",
    )
    yellow_stmt = select(func.count(ReportRecord.report_id)).where(
        ReportRecord.created_at >= cutoff,
        ReportRecord.overall_risk == "YELLOW",
    )
    green_stmt = select(func.count(ReportRecord.report_id)).where(
        ReportRecord.created_at >= cutoff,
        ReportRecord.overall_risk == "GREEN",
    )

    red_result = await session.execute(red_stmt)
    yellow_result = await session.execute(yellow_stmt)
    green_result = await session.execute(green_stmt)

    red = red_result.scalar() or 0
    yellow = yellow_result.scalar() or 0
    green = green_result.scalar() or 0
    total = red + yellow + green

    return RiskDistribution(
        red=red,
        yellow=yellow,
        green=green,
        red_percent=red / total * 100 if total > 0 else 0,
        yellow_percent=yellow / total * 100 if total > 0 else 0,
        green_percent=green / total * 100 if total > 0 else 0,
    )


@router.get("/reports-over-time", response_model=list[TimeSeriesPoint])
@limiter.limit(LIMITS["reports"])
async def get_reports_over_time(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session_dependency),
) -> list[TimeSeriesPoint]:
    """Get reports count over time."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Get all reports in range
    stmt = select(ReportRecord).where(ReportRecord.created_at >= cutoff)
    result = await session.execute(stmt)
    reports = result.scalars().all()

    # Group by date
    date_counts: dict[str, dict] = {}
    for report in reports:
        date_str = report.created_at.strftime("%Y-%m-%d")
        if date_str not in date_counts:
            date_counts[date_str] = {"count": 0, "red": 0, "yellow": 0, "green": 0}
        date_counts[date_str]["count"] += 1
        date_counts[date_str][report.overall_risk.lower()] += 1

    # Fill in missing dates
    points = []
    current = cutoff.date()
    end = datetime.now(UTC).date()
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        counts = date_counts.get(date_str, {"count": 0, "red": 0, "yellow": 0, "green": 0})
        points.append(
            TimeSeriesPoint(
                date=date_str,
                count=counts["count"],
                red=counts["red"],
                yellow=counts["yellow"],
                green=counts["green"],
            )
        )
        current += timedelta(days=1)

    return points


@router.get("/recruiter-activity", response_model=list[RecruiterActivity])
@limiter.limit(LIMITS["reports"])
async def get_recruiter_activity(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session_dependency),
) -> list[RecruiterActivity]:
    """Get top recruiters by activity."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Get analyze actions from audit log
    stmt = (
        select(
            AuditLogRecord.user_name,
            func.count(AuditLogRecord.id).label("count"),
            func.max(AuditLogRecord.created_at).label("last_active"),
        )
        .where(
            AuditLogRecord.action == "analyze",
            AuditLogRecord.created_at >= cutoff,
            AuditLogRecord.user_name.isnot(None),
        )
        .group_by(AuditLogRecord.user_name)
        .order_by(func.count(AuditLogRecord.id).desc())
        .limit(limit)
    )

    result = await session.execute(stmt)
    rows = result.all()

    return [
        RecruiterActivity(
            recruiter=row.user_name or "Unknown",
            total_analyses=row.count,
            last_active=row.last_active.isoformat() if row.last_active else None,
        )
        for row in rows
    ]


@router.get("/top-flags", response_model=dict)
@limiter.limit(LIMITS["reports"])
async def get_top_flags(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session_dependency),
) -> dict:
    """Get most common flags."""
    import json

    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Get all reports in range
    stmt = select(ReportRecord.flags_json).where(ReportRecord.created_at >= cutoff)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    # Count flags
    red_flags: dict[str, dict] = {}
    yellow_flags: dict[str, dict] = {}

    for flags_json in rows:
        try:
            flags = json.loads(flags_json)
            for flag in flags:
                code = flag.get("code", "UNKNOWN")
                title = flag.get("title", code)
                severity = flag.get("severity", "")

                if severity == "RED":
                    if code not in red_flags:
                        red_flags[code] = {"title": title, "count": 0}
                    red_flags[code]["count"] += 1
                elif severity == "YELLOW":
                    if code not in yellow_flags:
                        yellow_flags[code] = {"title": title, "count": 0}
                    yellow_flags[code]["count"] += 1
        except json.JSONDecodeError:
            continue

    # Sort and limit
    top_red = sorted(red_flags.items(), key=lambda x: x[1]["count"], reverse=True)[:limit]
    top_yellow = sorted(yellow_flags.items(), key=lambda x: x[1]["count"], reverse=True)[:limit]

    return {
        "red_flags": [
            TopFlag(code=code, title=data["title"], count=data["count"], severity="RED")
            for code, data in top_red
        ],
        "yellow_flags": [
            TopFlag(code=code, title=data["title"], count=data["count"], severity="YELLOW")
            for code, data in top_yellow
        ],
    }


@router.get("/dashboard", response_model=AnalyticsDashboard)
@limiter.limit(LIMITS["reports"])
async def get_dashboard(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session_dependency),
) -> AnalyticsDashboard:
    """Get full analytics dashboard data in one call."""
    overview = await get_overview_stats(request, session)
    risk_dist = await get_risk_distribution(request, days, session)
    time_series = await get_reports_over_time(request, days, session)
    recruiters = await get_recruiter_activity(request, days, 10, session)
    flags = await get_top_flags(request, days, 10, session)

    return AnalyticsDashboard(
        overview=overview,
        risk_distribution=risk_dist,
        reports_over_time=time_series,
        top_recruiters=recruiters,
        top_red_flags=flags["red_flags"],
        top_yellow_flags=flags["yellow_flags"],
    )
