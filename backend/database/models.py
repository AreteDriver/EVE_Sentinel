"""SQLAlchemy ORM models for report persistence."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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

    # Relationships
    annotations: Mapped[list["AnnotationRecord"]] = relationship(
        "AnnotationRecord",
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="AnnotationRecord.created_at.desc()",
    )


class AnnotationRecord(Base):
    """
    User annotation/note on a report.

    Allows recruiters to add comments, notes, or decisions to reports.
    """

    __tablename__ = "annotations"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign key to report
    report_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("reports.report_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Annotation content
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Annotation type for categorization
    annotation_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="note"
    )  # note, decision, warning, info

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationship back to report
    report: Mapped["ReportRecord"] = relationship("ReportRecord", back_populates="annotations")


class ShareRecord(Base):
    """
    Shareable link for a report.

    Allows creating public read-only links for sharing reports externally.
    """

    __tablename__ = "shares"

    # Primary key - the share token
    token: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Foreign key to report
    report_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("reports.report_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Share metadata
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Expiry and access control
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    max_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Status
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=True)  # SQLite bool

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WatchlistRecord(Base):
    """
    Watchlist entry for tracking characters over time.

    Allows recruiters to monitor specific characters for changes.
    """

    __tablename__ = "watchlist"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Character info
    character_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    character_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Watchlist metadata
    added_by: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal"
    )  # high, normal, low

    # Last known state
    last_risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_analysis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_analysis_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Alert settings
    alert_on_change: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=True
    )  # SQLite bool
    alert_threshold: Mapped[str] = mapped_column(
        String(20), nullable=False, default="any"
    )  # any, yellow, red

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLogRecord(Base):
    """
    Audit log entry for tracking user actions.

    Records who did what, when, and from where for security and compliance.
    """

    __tablename__ = "audit_logs"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Action details
    action: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    # Actions: analyze, view_report, create_share, revoke_share, add_watchlist,
    #          remove_watchlist, add_annotation, delete_annotation, login, logout, etc.

    # Actor information
    user_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 max length
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Target information
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Types: character, report, share, watchlist, annotation, user, etc.
    target_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    target_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Additional context as JSON
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Result
    success: Mapped[bool] = mapped_column(Integer, nullable=False, default=True)  # SQLite bool
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime, index=True, nullable=False, default=lambda: datetime.now(UTC)
    )

    # Composite indexes for common queries
    __table_args__ = (
        Index("idx_audit_user_time", "user_id", "created_at"),
        Index("idx_audit_action_time", "action", "created_at"),
        Index("idx_audit_target_time", "target_type", "target_id", "created_at"),
    )


class UserRecord(Base):
    """
    User account for role-based access control.

    Links to EVE SSO character for authentication.
    """

    __tablename__ = "users"

    # Primary key - EVE character ID
    character_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Character info
    character_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Role (admin, recruiter, viewer)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="viewer")

    # Status
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=True)  # SQLite bool

    # Metadata
    corporation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alliance_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Email notification preferences
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_on_watchlist_change: Mapped[bool] = mapped_column(Integer, nullable=False, default=True)
    email_on_red_alert: Mapped[bool] = mapped_column(Integer, nullable=False, default=True)
    email_on_yellow_alert: Mapped[bool] = mapped_column(Integer, nullable=False, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FlagRuleRecord(Base):
    """
    Custom flag rule defined by admins.

    Allows defining custom red/yellow/green flag conditions.
    """

    __tablename__ = "flag_rules"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Rule definition
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # Severity (RED, YELLOW, GREEN)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)

    # Condition type and parameters
    # Types: corp_history, alliance_member, character_age, kill_count, etc.
    condition_type: Mapped[str] = mapped_column(String(50), nullable=False)
    condition_params_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Message shown when flag triggers
    flag_message: Mapped[str] = mapped_column(Text, nullable=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # Metadata
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReportTagRecord(Base):
    """
    Tag applied to a report for organization.

    Allows tagging reports for bulk operations and filtering.
    """

    __tablename__ = "report_tags"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign key to report
    report_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("reports.report_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Tag info
    tag: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    added_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )

    # Unique constraint: one tag per report
    __table_args__ = (Index("idx_report_tag", "report_id", "tag", unique=True),)
