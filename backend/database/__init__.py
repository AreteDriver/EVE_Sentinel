"""Database persistence layer."""

from backend.database.models import (
    AnnotationRecord,
    AuditLogRecord,
    Base,
    ReportRecord,
    ShareRecord,
    UserRecord,
    WatchlistRecord,
)
from backend.database.repository import (
    AnnotationRepository,
    AuditLog,
    AuditLogRepository,
    ReportRepository,
    ShareRepository,
    User,
    UserRepository,
    WatchlistRepository,
)
from backend.database.session import (
    close_db,
    get_session,
    get_session_dependency,
    init_db,
)

__all__ = [
    "AnnotationRecord",
    "AnnotationRepository",
    "AuditLog",
    "AuditLogRecord",
    "AuditLogRepository",
    "Base",
    "ReportRecord",
    "ReportRepository",
    "ShareRecord",
    "ShareRepository",
    "User",
    "UserRecord",
    "UserRepository",
    "WatchlistRecord",
    "WatchlistRepository",
    "init_db",
    "close_db",
    "get_session",
    "get_session_dependency",
]
