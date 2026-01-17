"""Analysis report models."""

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .applicant import Applicant, Playstyle, SuspectedAlt
from .flags import FlagSeverity, RiskFlag


class OverallRisk(str, Enum):
    """Overall risk assessment."""

    RED = "RED"  # High risk - recommend reject
    YELLOW = "YELLOW"  # Moderate risk - needs review
    GREEN = "GREEN"  # Low risk - likely safe
    UNKNOWN = "UNKNOWN"  # Insufficient data


class ReportStatus(str, Enum):
    """Report processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisReport(BaseModel):
    """Complete recruitment analysis report."""

    # Report metadata
    report_id: UUID = Field(default_factory=uuid4)
    status: ReportStatus = ReportStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    requested_by: str | None = None  # Who requested the analysis

    # Subject
    character_id: int
    character_name: str

    # Risk assessment
    overall_risk: OverallRisk = OverallRisk.UNKNOWN
    confidence: float = 0.0  # 0.0 to 1.0

    # Detailed flags
    flags: list[RiskFlag] = Field(default_factory=list)
    red_flag_count: int = 0
    yellow_flag_count: int = 0
    green_flag_count: int = 0

    # Analysis results
    playstyle: Playstyle | None = None
    suspected_alts: list[SuspectedAlt] = Field(default_factory=list)

    # Recommendations
    recommendations: list[str] = Field(default_factory=list)

    # Full applicant data (optional, for detailed view)
    applicant_data: Applicant | None = None

    # Processing info
    analyzers_run: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    processing_time_ms: int | None = None

    def calculate_risk(self) -> None:
        """Calculate overall risk from flags."""
        self.red_flag_count = sum(1 for f in self.flags if f.severity == FlagSeverity.RED)
        self.yellow_flag_count = sum(1 for f in self.flags if f.severity == FlagSeverity.YELLOW)
        self.green_flag_count = sum(1 for f in self.flags if f.severity == FlagSeverity.GREEN)

        # Risk calculation logic
        if self.red_flag_count >= 2:
            self.overall_risk = OverallRisk.RED
            self.confidence = min(0.9, 0.5 + (self.red_flag_count * 0.1))
        elif self.red_flag_count == 1:
            self.overall_risk = OverallRisk.YELLOW
            self.confidence = 0.7
        elif self.yellow_flag_count >= 3:
            self.overall_risk = OverallRisk.YELLOW
            self.confidence = 0.6
        elif self.yellow_flag_count >= 1:
            if self.green_flag_count >= 3:
                self.overall_risk = OverallRisk.GREEN
                self.confidence = 0.6
            else:
                self.overall_risk = OverallRisk.YELLOW
                self.confidence = 0.5
        elif self.green_flag_count >= 2:
            self.overall_risk = OverallRisk.GREEN
            self.confidence = min(0.85, 0.5 + (self.green_flag_count * 0.1))
        else:
            self.overall_risk = OverallRisk.UNKNOWN
            self.confidence = 0.3


class ReportSummary(BaseModel):
    """Lightweight report summary for listings."""

    report_id: UUID
    character_id: int
    character_name: str
    overall_risk: OverallRisk
    confidence: float
    red_flag_count: int
    yellow_flag_count: int
    green_flag_count: int
    created_at: datetime
    status: ReportStatus


class BatchAnalysisRequest(BaseModel):
    """Request to analyze multiple characters."""

    character_ids: list[int]
    requested_by: str | None = None
    priority: str = "normal"  # "high", "normal", "low"


class BatchAnalysisResult(BaseModel):
    """Result of batch analysis."""

    total_requested: int
    completed: int
    failed: int
    reports: list[ReportSummary] = Field(default_factory=list)
