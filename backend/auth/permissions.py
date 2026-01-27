"""Role-based access control and permissions."""

from collections.abc import Callable
from enum import Enum

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import User, UserRepository, get_session_dependency


class Role(str, Enum):
    """User roles with increasing privilege levels."""

    VIEWER = "viewer"  # Can view reports
    RECRUITER = "recruiter"  # Can analyze and manage watchlist
    ADMIN = "admin"  # Full access including user management


# Role hierarchy - higher roles include permissions of lower roles
ROLE_HIERARCHY = {
    Role.VIEWER: 0,
    Role.RECRUITER: 1,
    Role.ADMIN: 2,
}


def has_role_level(user_role: str, required_role: Role) -> bool:
    """Check if user's role meets or exceeds the required level."""
    try:
        user_level = ROLE_HIERARCHY.get(Role(user_role), -1)
        required_level = ROLE_HIERARCHY[required_role]
        return user_level >= required_level
    except ValueError:
        return False


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> User | None:
    """
    Get the current authenticated user from session.

    Returns None if not authenticated (for optional auth endpoints).
    """
    if not hasattr(request, "session"):
        return None

    character_id = request.session.get("character_id")
    if not character_id:
        return None

    repo = UserRepository(session)
    return await repo.get_by_id(character_id)


async def require_auth(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> User:
    """
    Require authentication - raises 401 if not logged in.

    Use as dependency: user: User = Depends(require_auth)
    """
    user = await get_current_user(request, session)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Account is disabled",
        )
    return user


async def require_viewer(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> User:
    """Require at least viewer role."""
    user = await require_auth(request, session)
    if not has_role_level(user.role, Role.VIEWER):
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions",
        )
    return user


async def require_recruiter(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> User:
    """Require at least recruiter role."""
    user = await require_auth(request, session)
    if not has_role_level(user.role, Role.RECRUITER):
        raise HTTPException(
            status_code=403,
            detail="Recruiter access required",
        )
    return user


async def require_admin(
    request: Request,
    session: AsyncSession = Depends(get_session_dependency),
) -> User:
    """Require admin role."""
    user = await require_auth(request, session)
    if not has_role_level(user.role, Role.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )
    return user


def require_role(role: Role) -> Callable:
    """
    Factory for role requirement dependencies.

    Usage:
        @router.get("/endpoint")
        async def endpoint(user: User = Depends(require_role(Role.ADMIN))):
            ...
    """

    async def dependency(
        request: Request,
        session: AsyncSession = Depends(get_session_dependency),
    ) -> User:
        user = await require_auth(request, session)
        if not has_role_level(user.role, role):
            raise HTTPException(
                status_code=403,
                detail=f"{role.value.title()} access required",
            )
        return user

    return dependency


class PermissionChecker:
    """
    Permission checker for granular access control.

    Usage:
        checker = PermissionChecker()

        @router.get("/reports/{report_id}")
        async def get_report(
            report_id: str,
            user: User = Depends(require_auth),
        ):
            if not await checker.can_view_report(user, report_id):
                raise HTTPException(403, "Cannot view this report")
    """

    async def can_analyze(self, user: User) -> bool:
        """Check if user can perform character analysis."""
        return has_role_level(user.role, Role.RECRUITER)

    async def can_view_reports(self, user: User) -> bool:
        """Check if user can view reports."""
        return has_role_level(user.role, Role.VIEWER)

    async def can_manage_watchlist(self, user: User) -> bool:
        """Check if user can add/remove watchlist entries."""
        return has_role_level(user.role, Role.RECRUITER)

    async def can_create_shares(self, user: User) -> bool:
        """Check if user can create share links."""
        return has_role_level(user.role, Role.RECRUITER)

    async def can_view_audit_logs(self, user: User) -> bool:
        """Check if user can view audit logs."""
        return has_role_level(user.role, Role.ADMIN)

    async def can_manage_users(self, user: User) -> bool:
        """Check if user can manage other users."""
        return has_role_level(user.role, Role.ADMIN)

    async def can_manage_scheduler(self, user: User) -> bool:
        """Check if user can control the scheduler."""
        return has_role_level(user.role, Role.ADMIN)


# Global permission checker instance
permissions = PermissionChecker()
