"""Database persistence layer."""

from backend.database.models import (
    AnnotationRecord,
    Base,
    ReportRecord,
    ShareRecord,
    WatchlistRecord,
)
from backend.database.repository import (
    AnnotationRepository,
    ReportRepository,
    ShareRepository,
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
    "Base",
    "ReportRecord",
    "ReportRepository",
    "ShareRecord",
    "ShareRepository",
    "WatchlistRecord",
    "WatchlistRepository",
    "init_db",
    "close_db",
    "get_session",
    "get_session_dependency",
]
