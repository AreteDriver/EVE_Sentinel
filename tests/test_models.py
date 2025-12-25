"""Test model definitions."""

import pytest

from backend.models.flags import FlagSeverity, RiskFlag, FlagCategory, RedFlags
from backend.models.report import AnalysisReport, OverallRisk


def test_risk_flag_creation():
    """Test creating a risk flag."""
    flag = RiskFlag(
        severity=FlagSeverity.RED,
        category=FlagCategory.CORP_HISTORY,
        code=RedFlags.KNOWN_SPY_CORP,
        reason="Test reason",
    )
    assert flag.severity == FlagSeverity.RED
    assert flag.code == "KNOWN_SPY_CORP"


def test_report_risk_calculation():
    """Test report risk calculation."""
    report = AnalysisReport(
        character_id=12345,
        character_name="Test Pilot",
    )

    # Add some flags
    report.flags = [
        RiskFlag(
            severity=FlagSeverity.RED,
            category=FlagCategory.CORP_HISTORY,
            code=RedFlags.KNOWN_SPY_CORP,
            reason="Was in hostile corp",
        ),
        RiskFlag(
            severity=FlagSeverity.RED,
            category=FlagCategory.KILLBOARD,
            code=RedFlags.AWOX_HISTORY,
            reason="AWOX kills detected",
        ),
    ]

    report.calculate_risk()

    assert report.overall_risk == OverallRisk.RED
    assert report.red_flag_count == 2
    assert report.confidence >= 0.5
