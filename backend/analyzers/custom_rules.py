"""Custom flag rules analyzer."""

from backend.database import FlagRuleRepository, get_session
from backend.models.applicant import Applicant
from backend.models.flags import FlagCategory, FlagSeverity, RiskFlag

from .base import BaseAnalyzer


class CustomRulesAnalyzer(BaseAnalyzer):
    """
    Analyzer that applies custom user-defined flag rules.

    Evaluates applicants against custom rules defined in the database
    and generates flags for matching conditions.
    """

    name = "custom_rules"
    description = "Custom flag rules defined by administrators"
    requires_auth = False

    async def analyze(self, applicant: Applicant) -> list[RiskFlag]:
        """Analyze applicant against all active custom rules."""
        flags: list[RiskFlag] = []

        async with get_session() as session:
            repo = FlagRuleRepository(session)
            rules = await repo.get_active_rules()

            for rule in rules:
                if self._evaluate_rule(rule, applicant):
                    flags.append(self._create_flag(rule))

        return flags

    def _evaluate_rule(self, rule, applicant: Applicant) -> bool:
        """
        Evaluate if a rule condition matches the applicant.

        Returns True if the rule should trigger.
        """
        condition_type = rule.condition_type
        params = rule.condition_params

        try:
            if condition_type == "corp_member":
                # Check if character is currently in specific corp
                corp_ids = params.get("corp_ids", [])
                if applicant.corporation_id and applicant.corporation_id in corp_ids:
                    return True

            elif condition_type == "alliance_member":
                # Check if character is in specific alliance
                alliance_ids = params.get("alliance_ids", [])
                if applicant.alliance_id and applicant.alliance_id in alliance_ids:
                    return True

            elif condition_type == "corp_history":
                # Check if character was ever in specific corps
                corp_ids = params.get("corp_ids", [])
                if applicant.corp_history:
                    for entry in applicant.corp_history:
                        if entry.corporation_id in corp_ids:
                            return True

            elif condition_type == "character_age":
                # Check character age (days)
                operator = params.get("operator", "lt")  # lt, gt, eq
                days = params.get("days", 30)
                if applicant.character_age_days is not None:
                    if operator == "lt" and applicant.character_age_days < days:
                        return True
                    elif operator == "gt" and applicant.character_age_days > days:
                        return True
                    elif operator == "eq" and applicant.character_age_days == days:
                        return True

            elif condition_type == "security_status":
                # Check security status
                operator = params.get("operator", "lt")
                value = params.get("value", 0)
                if applicant.security_status is not None:
                    if operator == "lt" and applicant.security_status < value:
                        return True
                    elif operator == "gt" and applicant.security_status > value:
                        return True
                    elif operator == "eq" and applicant.security_status == value:
                        return True

            elif condition_type == "kill_count":
                # Check total kills
                operator = params.get("operator", "gt")
                count = params.get("count", 100)
                if applicant.killboard:
                    kills = applicant.killboard.kills_total or 0
                    if operator == "lt" and kills < count:
                        return True
                    elif operator == "gt" and kills > count:
                        return True

            elif condition_type == "death_count":
                # Check total deaths
                operator = params.get("operator", "gt")
                count = params.get("count", 100)
                if applicant.killboard:
                    deaths = applicant.killboard.deaths_total or 0
                    if operator == "lt" and deaths < count:
                        return True
                    elif operator == "gt" and deaths > count:
                        return True

            elif condition_type == "zkill_danger":
                # Check zKillboard danger ratio
                operator = params.get("operator", "gt")
                value = params.get("value", 50)
                if applicant.killboard and applicant.killboard.danger_ratio is not None:
                    if operator == "lt" and applicant.killboard.danger_ratio < value:
                        return True
                    elif operator == "gt" and applicant.killboard.danger_ratio > value:
                        return True

        except Exception:
            # If evaluation fails, don't trigger the rule
            pass

        return False

    def _create_flag(self, rule) -> RiskFlag:
        """Create a RiskFlag from a matched rule."""
        severity_map = {
            "RED": FlagSeverity.RED,
            "YELLOW": FlagSeverity.YELLOW,
            "GREEN": FlagSeverity.GREEN,
        }

        return RiskFlag(
            severity=severity_map.get(rule.severity, FlagSeverity.YELLOW),
            category=FlagCategory.GENERAL,
            code=rule.code,
            reason=rule.flag_message,
            evidence={
                "rule_name": rule.name,
                "rule_id": rule.id,
                "condition_type": rule.condition_type,
            },
            confidence=1.0,  # Custom rules are deterministic
        )
