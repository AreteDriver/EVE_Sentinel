"""User management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import User, UserRepository, get_session_dependency
from backend.rate_limit import LIMITS, limiter
from backend.services import AuditService

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class CreateUserRequest(BaseModel):
    """Request to create a user."""

    character_id: int
    character_name: str
    role: str = "viewer"
    corporation_id: int | None = None
    alliance_id: int | None = None


class UpdateUserRequest(BaseModel):
    """Request to update a user."""

    role: str | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    """Response model for user."""

    character_id: int
    character_name: str
    role: str
    is_active: bool
    corporation_id: int | None = None
    alliance_id: int | None = None
    created_at: str
    last_login_at: str | None = None


class UserStatsResponse(BaseModel):
    """Response model for user statistics."""

    total_users: int
    active_users: int
    admins: int
    recruiters: int
    viewers: int


def _to_response(user: User) -> UserResponse:
    """Convert User to response model."""
    return UserResponse(
        character_id=user.character_id,
        character_name=user.character_name,
        role=user.role,
        is_active=user.is_active,
        corporation_id=user.corporation_id,
        alliance_id=user.alliance_id,
        created_at=user.created_at.isoformat(),
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


@router.get("", response_model=list[UserResponse])
@limiter.limit(LIMITS["admin"])
async def list_users(
    request: Request,
    role: str | None = Query(default=None, description="Filter by role"),
    is_active: bool | None = Query(default=None, description="Filter by active status"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session_dependency),
) -> list[UserResponse]:
    """
    List all users.

    Requires admin access.
    """
    offset = (page - 1) * limit
    repo = UserRepository(session)
    users = await repo.list_users(
        role=role,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return [_to_response(u) for u in users]


@router.get("/stats", response_model=UserStatsResponse)
@limiter.limit(LIMITS["admin"])
async def get_user_stats(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> UserStatsResponse:
    """Get user statistics."""
    repo = UserRepository(session)

    total = await repo.count_users()
    active = await repo.count_users(is_active=True)
    admins = await repo.count_users(role="admin")
    recruiters = await repo.count_users(role="recruiter")
    viewers = await repo.count_users(role="viewer")

    return UserStatsResponse(
        total_users=total,
        active_users=active,
        admins=admins,
        recruiters=recruiters,
        viewers=viewers,
    )


@router.get("/roles", response_model=list[str])
async def list_roles(request: Request) -> list[str]:
    """List available roles."""
    return UserRepository.ROLES


@router.get("/{character_id}", response_model=UserResponse)
@limiter.limit(LIMITS["admin"])
async def get_user(
    request: Request,
    character_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> UserResponse:
    """Get a user by character ID."""
    repo = UserRepository(session)
    user = await repo.get_by_id(character_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return _to_response(user)


@router.post("", response_model=UserResponse, status_code=201)
@limiter.limit(LIMITS["admin"])
async def create_user(
    request: Request,
    user_request: CreateUserRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> UserResponse:
    """
    Create a new user.

    Requires admin access.
    """
    repo = UserRepository(session)

    # Check if user already exists
    existing = await repo.get_by_id(user_request.character_id)
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    try:
        user = await repo.create(
            character_id=user_request.character_id,
            character_name=user_request.character_name,
            role=user_request.role,
            corporation_id=user_request.corporation_id,
            alliance_id=user_request.alliance_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Audit log
    audit = AuditService(session, request)
    await audit.log_user_create(
        character_id=user.character_id,
        character_name=user.character_name,
        role=user.role,
    )

    return _to_response(user)


@router.patch("/{character_id}", response_model=UserResponse)
@limiter.limit(LIMITS["admin"])
async def update_user(
    request: Request,
    character_id: int,
    update_request: UpdateUserRequest,
    session: AsyncSession = Depends(get_session_dependency),
) -> UserResponse:
    """
    Update a user's role or status.

    Requires admin access.
    """
    repo = UserRepository(session)
    user = await repo.get_by_id(character_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    changes = {}

    # Update role if provided
    if update_request.role is not None:
        try:
            user = await repo.update_role(character_id, update_request.role)
            changes["role"] = update_request.role
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Update status if provided
    if update_request.is_active is not None:
        user = await repo.update_status(character_id, update_request.is_active)
        changes["is_active"] = update_request.is_active

    if not user:
        raise HTTPException(status_code=404, detail="User not found after update")

    # Audit log
    if changes:
        audit = AuditService(session, request)
        await audit.log_user_update(
            character_id=user.character_id,
            character_name=user.character_name,
            changes=changes,
        )

    return _to_response(user)


@router.delete("/{character_id}", status_code=204)
@limiter.limit(LIMITS["admin"])
async def delete_user(
    request: Request,
    character_id: int,
    session: AsyncSession = Depends(get_session_dependency),
) -> None:
    """
    Delete a user.

    Requires admin access.
    """
    repo = UserRepository(session)
    user = await repo.get_by_id(character_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    deleted = await repo.delete(character_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")

    # Audit log
    audit = AuditService(session, request)
    await audit.log_user_delete(
        character_id=user.character_id,
        character_name=user.character_name,
    )
