"""Audit logging service for easy integration."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import AuditLog, AuditLogRepository


def get_client_info(request: Request) -> dict:
    """Extract client information from request for audit logging."""
    # Get IP address (handle proxies)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip_address = forwarded.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else None

    # Get user agent
    user_agent = request.headers.get("user-agent", "")[:500]

    # Get user from session if available
    user_id = None
    user_name = None
    if hasattr(request, "session"):
        session_data = request.session
        user_id = session_data.get("character_id")
        if user_id:
            user_id = str(user_id)
        user_name = session_data.get("character_name")

    return {
        "ip_address": ip_address,
        "user_agent": user_agent,
        "user_id": user_id,
        "user_name": user_name,
    }


class AuditService:
    """
    Service for logging audit events.

    Provides convenient methods for common audit actions.
    """

    def __init__(self, session: AsyncSession, request: Request | None = None) -> None:
        self._repo = AuditLogRepository(session)
        self._client_info = get_client_info(request) if request else {}

    async def log(
        self,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        target_name: str | None = None,
        details: dict | None = None,
        success: bool = True,
        error_message: str | None = None,
        user_id: str | None = None,
        user_name: str | None = None,
    ) -> AuditLog:
        """Log an audit event."""
        return await self._repo.log(
            action=action,
            user_id=user_id or self._client_info.get("user_id"),
            user_name=user_name or self._client_info.get("user_name"),
            ip_address=self._client_info.get("ip_address"),
            user_agent=self._client_info.get("user_agent"),
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            details=details,
            success=success,
            error_message=error_message,
        )

    # Convenience methods for common actions

    async def log_analyze(
        self,
        character_id: int,
        character_name: str,
        report_id: str,
        success: bool = True,
        error: str | None = None,
    ) -> AuditLog:
        """Log a character analysis."""
        return await self.log(
            action="analyze",
            target_type="character",
            target_id=str(character_id),
            target_name=character_name,
            details={"report_id": report_id},
            success=success,
            error_message=error,
        )

    async def log_batch_analyze(
        self,
        character_count: int,
        success_count: int,
        fail_count: int,
    ) -> AuditLog:
        """Log a batch analysis."""
        return await self.log(
            action="batch_analyze",
            target_type="batch",
            details={
                "character_count": character_count,
                "success_count": success_count,
                "fail_count": fail_count,
            },
        )

    async def log_view_report(
        self,
        report_id: str,
        character_name: str,
    ) -> AuditLog:
        """Log viewing a report."""
        return await self.log(
            action="view_report",
            target_type="report",
            target_id=report_id,
            target_name=character_name,
        )

    async def log_delete_report(
        self,
        report_id: str,
        character_name: str,
    ) -> AuditLog:
        """Log deleting a report."""
        return await self.log(
            action="delete_report",
            target_type="report",
            target_id=report_id,
            target_name=character_name,
        )

    async def log_create_share(
        self,
        share_token: str,
        report_id: str,
    ) -> AuditLog:
        """Log creating a share link."""
        return await self.log(
            action="create_share",
            target_type="report",
            target_id=report_id,
            details={"share_token": share_token},
        )

    async def log_revoke_share(
        self,
        share_token: str,
    ) -> AuditLog:
        """Log revoking a share link."""
        return await self.log(
            action="revoke_share",
            target_type="share",
            target_id=share_token,
        )

    async def log_view_shared(
        self,
        share_token: str,
        report_id: str,
    ) -> AuditLog:
        """Log viewing a shared report."""
        return await self.log(
            action="view_shared",
            target_type="share",
            target_id=share_token,
            details={"report_id": report_id},
        )

    async def log_add_watchlist(
        self,
        character_id: int,
        character_name: str,
    ) -> AuditLog:
        """Log adding a character to watchlist."""
        return await self.log(
            action="add_watchlist",
            target_type="character",
            target_id=str(character_id),
            target_name=character_name,
        )

    async def log_remove_watchlist(
        self,
        character_id: int,
        character_name: str,
    ) -> AuditLog:
        """Log removing a character from watchlist."""
        return await self.log(
            action="remove_watchlist",
            target_type="character",
            target_id=str(character_id),
            target_name=character_name,
        )

    async def log_add_annotation(
        self,
        report_id: str,
        annotation_id: int,
    ) -> AuditLog:
        """Log adding an annotation."""
        return await self.log(
            action="add_annotation",
            target_type="report",
            target_id=report_id,
            details={"annotation_id": annotation_id},
        )

    async def log_delete_annotation(
        self,
        report_id: str,
        annotation_id: int,
    ) -> AuditLog:
        """Log deleting an annotation."""
        return await self.log(
            action="delete_annotation",
            target_type="report",
            target_id=report_id,
            details={"annotation_id": annotation_id},
        )

    async def log_login(
        self,
        character_id: int,
        character_name: str,
    ) -> AuditLog:
        """Log user login."""
        return await self.log(
            action="login",
            target_type="user",
            target_id=str(character_id),
            target_name=character_name,
            user_id=str(character_id),
            user_name=character_name,
        )

    async def log_logout(self) -> AuditLog:
        """Log user logout."""
        return await self.log(
            action="logout",
            target_type="user",
        )

    async def log_export_pdf(
        self,
        report_id: str,
        character_name: str,
    ) -> AuditLog:
        """Log PDF export."""
        return await self.log(
            action="export_pdf",
            target_type="report",
            target_id=report_id,
            target_name=character_name,
        )

    async def log_export_csv(
        self,
        report_id: str,
        character_name: str,
    ) -> AuditLog:
        """Log CSV export."""
        return await self.log(
            action="export_csv",
            target_type="report",
            target_id=report_id,
            target_name=character_name,
        )

    async def log_user_create(
        self,
        character_id: int,
        character_name: str,
        role: str,
    ) -> AuditLog:
        """Log user creation."""
        return await self.log(
            action="user_create",
            target_type="user",
            target_id=str(character_id),
            target_name=character_name,
            details={"role": role},
        )

    async def log_user_update(
        self,
        character_id: int,
        character_name: str,
        changes: dict,
    ) -> AuditLog:
        """Log user update."""
        return await self.log(
            action="user_update",
            target_type="user",
            target_id=str(character_id),
            target_name=character_name,
            details=changes,
        )

    async def log_user_delete(
        self,
        character_id: int,
        character_name: str,
    ) -> AuditLog:
        """Log user deletion."""
        return await self.log(
            action="user_delete",
            target_type="user",
            target_id=str(character_id),
            target_name=character_name,
        )
