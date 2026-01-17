"""SQLAlchemy ORM models for report persistence."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


class ReportRecord(Base):
    """
    Stored analysis report.

    Complex nested objects (flags, applicant_data) stored as JSON
    for simplicity - avoids complex relational mapping while still
    enabling core query patterns.
    """

    __tablename__ = "reports"

    # Primary key - store UUID as string for SQLite compatibility
    report_id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Core identifiers (indexed for queries)
    character_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    character_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Risk assessment (indexed for filtering)
    overall_risk: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    # Timestamps (indexed for sorting/filtering)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Metadata
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Flag counts (for quick filtering without deserializing JSON)
    red_flag_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    yellow_flag_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    green_flag_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Complex data as JSON
    flags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recommendations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    analyzers_run_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    errors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    applicant_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    playstyle_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspected_alts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Composite index for common query patterns
    __table_args__ = (
        Index("idx_char_created", "character_id", "created_at"),
        Index("idx_risk_created", "overall_risk", "created_at"),
    )
