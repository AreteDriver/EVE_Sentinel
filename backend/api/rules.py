"""Custom flag rules API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import FlagRule, FlagRuleRepository, get_session_dependency
from backend.rate_limit import LIMITS, limiter

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])


class CreateRuleRequest(BaseModel):
    """Request to create a custom flag rule."""

    name: str
    code: str
    severity: str  # RED, YELLOW, GREEN
    condition_type: str
    condition_params: dict
    flag_message: str
    description: str | None = None
    priority: int = 100


class UpdateRuleRequest(BaseModel):
    """Request to update a flag rule."""

    name: str | None = None
    description: str | None = None
    severity: str | None = None
    condition_type: str | None = None
    condition_params: dict | None = None
    flag_message: str | None = None
    is_active: bool | None = None
    priority: int | None = None


class RuleResponse(BaseModel):
    """Response model for flag rule."""

    id: int
    name: str
    description: str | None = None
    code: str
    severity: str
    condition_type: str
    condition_params: dict
    flag_message: str
    is_active: bool
    priority: int
    created_by: str
    created_at: str
    updated_at: str | None = None


def _to_response(rule: FlagRule) -> RuleResponse:
    """Convert FlagRule to response model."""
    return RuleResponse(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        code=rule.code,
        severity=rule.severity,
        condition_type=rule.condition_type,
        condition_params=rule.condition_params,
        flag_message=rule.flag_message,
        is_active=rule.is_active,
        priority=rule.priority,
        created_by=rule.created_by,
        created_at=rule.created_at.isoformat(),
        updated_at=rule.updated_at.isoformat() if rule.updated_at else None,
    )


@router.get("", response_model=list[RuleResponse])
@limiter.limit(LIMITS["admin"])
async def list_rules(
    request: Request,
    active_only: bool = Query(default=False, description="Only show active rules"),
    severity: str | None = Query(default=None, description="Filter by severity"),
    session: AsyncSession = Depends(get_session_dependency),
) -> list[RuleResponse]:
    """
    List all custom flag rules.

    Requires admin access.
    """
    repo = FlagRuleRepository(session)
    rules = await repo.list_rules(active_only=active_only, severity=severity)
    return [_to_response(r) for r in rules]


@router.get("/condition-types")
async def list_condition_types(request: Request) -> list[dict]:
    """
    List available condition types for rules.

    Returns condition types with descriptions and parameter schemas.
    """
    return [
        {
            "type": "corp_member",
            "name": "Corporation Member",
            "description": "Character is currently a member of specific corporation(s)",
            "params": {"corp_ids": "list[int] - Corporation IDs to check"},
        },
        {
            "type": "alliance_member",
            "name": "Alliance Member",
            "description": "Character is currently in specific alliance(s)",
            "params": {"alliance_ids": "list[int] - Alliance IDs to check"},
        },
        {
            "type": "corp_history",
            "name": "Corporation History",
            "description": "Character was ever a member of specific corporation(s)",
            "params": {"corp_ids": "list[int] - Corporation IDs to check history for"},
        },
        {
            "type": "character_age",
            "name": "Character Age",
            "description": "Character age comparison (in days)",
            "params": {
                "operator": "str - Comparison: 'lt' (less than), 'gt' (greater than), 'eq' (equal)",
                "days": "int - Number of days to compare",
            },
        },
        {
            "type": "security_status",
            "name": "Security Status",
            "description": "Character's security status comparison",
            "params": {
                "operator": "str - Comparison: 'lt', 'gt', 'eq'",
                "value": "float - Security status value (-10.0 to 10.0)",
            },
        },
        {
            "type": "kill_count",
            "name": "Kill Count",
            "description": "Total kills comparison",
            "params": {
                "operator": "str - Comparison: 'lt', 'gt'",
                "count": "int - Number of kills to compare",
            },
        },
        {
            "type": "death_count",
            "name": "Death Count",
            "description": "Total deaths comparison",
            "params": {
                "operator": "str - Comparison: 'lt', 'gt'",
                "count": "int - Number of deaths to compare",
            },
        },
        {
            "type": "zkill_danger",
            "name": "zKillboard Danger Ratio",
            "description": "zKillboard danger ratio comparison (0-100)",
            "params": {
                "operator": "str - Comparison: 'lt', 'gt'",
                "value": "int - Danger ratio value (0-100)",
            },
        },
    ]


@router.get("/{rule_id}", response_model=RuleResponse)
@limiter.limit(LIMITS["admin"])
async def get_rule(
    request: Request,
    rule_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> RuleResponse:
    """Get a specific flag rule by ID."""
    repo = FlagRuleRepository(session)
    rule = await repo.get_by_id(rule_id)

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    return _to_response(rule)


@router.post("", response_model=RuleResponse, status_code=201)
@limiter.limit(LIMITS["admin"])
async def create_rule(
    request: Request,
    rule_request: CreateRuleRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> RuleResponse:
    """
    Create a new custom flag rule.

    Requires admin access.
    """
    repo = FlagRuleRepository(session)

    # Validate severity
    if rule_request.severity.upper() not in ["RED", "YELLOW", "GREEN"]:
        raise HTTPException(
            status_code=400,
            detail="Severity must be RED, YELLOW, or GREEN",
        )

    # Validate condition type
    if rule_request.condition_type not in FlagRuleRepository.CONDITION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid condition type. Must be one of: {FlagRuleRepository.CONDITION_TYPES}",
        )

    # Check if code already exists
    existing = await repo.get_by_code(rule_request.code)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Rule with code '{rule_request.code}' already exists",
        )

    # TODO: Get created_by from session
    created_by = "admin"

    rule = await repo.create(
        name=rule_request.name,
        code=rule_request.code,
        severity=rule_request.severity,
        condition_type=rule_request.condition_type,
        condition_params=rule_request.condition_params,
        flag_message=rule_request.flag_message,
        created_by=created_by,
        description=rule_request.description,
        priority=rule_request.priority,
    )

    return _to_response(rule)


@router.patch("/{rule_id}", response_model=RuleResponse)
@limiter.limit(LIMITS["admin"])
async def update_rule(
    request: Request,
    rule_id: int,
    update_request: UpdateRuleRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> RuleResponse:
    """
    Update a flag rule.

    Requires admin access.
    """
    repo = FlagRuleRepository(session)

    # Validate severity if provided
    if update_request.severity and update_request.severity.upper() not in ["RED", "YELLOW", "GREEN"]:
        raise HTTPException(
            status_code=400,
            detail="Severity must be RED, YELLOW, or GREEN",
        )

    # Validate condition type if provided
    if update_request.condition_type and update_request.condition_type not in FlagRuleRepository.CONDITION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid condition type. Must be one of: {FlagRuleRepository.CONDITION_TYPES}",
        )

    rule = await repo.update(
        rule_id=rule_id,
        name=update_request.name,
        description=update_request.description,
        severity=update_request.severity,
        condition_type=update_request.condition_type,
        condition_params=update_request.condition_params,
        flag_message=update_request.flag_message,
        is_active=update_request.is_active,
        priority=update_request.priority,
    )

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    return _to_response(rule)


@router.delete("/{rule_id}", status_code=204)
@limiter.limit(LIMITS["admin"])
async def delete_rule(
    request: Request,
    rule_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> None:
    """
    Delete a flag rule.

    Requires admin access.
    """
    repo = FlagRuleRepository(session)
    deleted = await repo.delete(rule_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")


@router.post("/{rule_id}/toggle", response_model=RuleResponse)
@limiter.limit(LIMITS["admin"])
async def toggle_rule(
    request: Request,
    rule_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> RuleResponse:
    """
    Toggle a rule's active status.

    Requires admin access.
    """
    repo = FlagRuleRepository(session)
    rule = await repo.get_by_id(rule_id)

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    updated = await repo.update(rule_id=rule_id, is_active=not rule.is_active)

    if not updated:
        raise HTTPException(status_code=404, detail="Rule not found after update")

    return _to_response(updated)
