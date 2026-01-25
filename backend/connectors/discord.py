"""Discord webhook client for sending recruitment alerts."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

import httpx

from backend.models.report import AnalysisReport, OverallRisk


class WebhookColor(int, Enum):
    """Discord embed colors for risk levels."""

    RED = 0xE74C3C  # High risk
    YELLOW = 0xF39C12  # Moderate risk
    GREEN = 0x2ECC71  # Low risk
    GRAY = 0x95A5A6  # Unknown


class DiscordWebhook:
    """
    Client for sending recruitment alerts to Discord.

    Sends formatted embeds with risk assessment summaries.
    """

    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url = webhook_url
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_color(self, risk: OverallRisk) -> int:
        """Get embed color for risk level."""
        colors = {
            OverallRisk.RED: WebhookColor.RED,
            OverallRisk.YELLOW: WebhookColor.YELLOW,
            OverallRisk.GREEN: WebhookColor.GREEN,
            OverallRisk.UNKNOWN: WebhookColor.GRAY,
        }
        return colors.get(risk, WebhookColor.GRAY)

    def _get_risk_emoji(self, risk: OverallRisk) -> str:
        """Get emoji for risk level."""
        emojis = {
            OverallRisk.RED: "🔴",
            OverallRisk.YELLOW: "🟡",
            OverallRisk.GREEN: "🟢",
            OverallRisk.UNKNOWN: "⚪",
        }
        return emojis.get(risk, "⚪")

    def _build_embed(self, report: AnalysisReport) -> dict[str, Any]:
        """Build Discord embed from analysis report."""
        risk_emoji = self._get_risk_emoji(report.overall_risk)
        color = self._get_color(report.overall_risk)

        # Build fields
        fields = [
            {
                "name": "Risk Assessment",
                "value": (
                    f"{risk_emoji} **{report.overall_risk.value}** "
                    f"(Confidence: {report.confidence:.0%})"
                ),
                "inline": True,
            },
            {
                "name": "Flags",
                "value": (
                    f"🔴 {report.red_flag_count} | 🟡 {report.yellow_flag_count} | "
                    f"🟢 {report.green_flag_count}"
                ),
                "inline": True,
            },
        ]

        # Add current corp/alliance if available
        if report.applicant_data:
            corp_info = report.applicant_data.corporation_name or "Unknown"
            if report.applicant_data.alliance_name:
                corp_info += f" [{report.applicant_data.alliance_name}]"
            fields.append(
                {
                    "name": "Current Corporation",
                    "value": corp_info,
                    "inline": False,
                }
            )

        # Add red flags summary
        red_flags = [f for f in report.flags if f.severity.value == "RED"]
        if red_flags:
            flag_text = "\n".join(f"• {f.reason}" for f in red_flags[:5])
            if len(red_flags) > 5:
                flag_text += f"\n*...and {len(red_flags) - 5} more*"
            fields.append(
                {
                    "name": "🚨 Red Flags",
                    "value": flag_text,
                    "inline": False,
                }
            )

        # Add yellow flags summary
        yellow_flags = [f for f in report.flags if f.severity.value == "YELLOW"]
        if yellow_flags:
            flag_text = "\n".join(f"• {f.reason}" for f in yellow_flags[:3])
            if len(yellow_flags) > 3:
                flag_text += f"\n*...and {len(yellow_flags) - 3} more*"
            fields.append(
                {
                    "name": "⚠️ Yellow Flags",
                    "value": flag_text,
                    "inline": False,
                }
            )

        # Add recommendations
        if report.recommendations:
            rec_text = "\n".join(f"• {r}" for r in report.recommendations[:3])
            fields.append(
                {
                    "name": "📋 Recommendations",
                    "value": rec_text,
                    "inline": False,
                }
            )

        # Build the embed
        embed = {
            "title": f"Recruitment Analysis: {report.character_name}",
            "url": f"https://zkillboard.com/character/{report.character_id}/",
            "color": color,
            "fields": fields,
            "footer": {"text": f"EVE Sentinel • Requested by {report.requested_by or 'Unknown'}"},
            "timestamp": datetime.now(UTC).isoformat(),
        }

        return embed

    async def send_report(
        self,
        report: AnalysisReport,
        webhook_url: str | None = None,
        mention_role: str | None = None,
    ) -> bool:
        """
        Send an analysis report to Discord.

        Args:
            report: The analysis report to send
            webhook_url: Override webhook URL (uses instance default if not provided)
            mention_role: Optional role ID to mention (e.g., "123456789")

        Returns:
            True if sent successfully, False otherwise
        """
        url = webhook_url or self.webhook_url
        if not url:
            return False

        embed = self._build_embed(report)

        # Build message content
        content = None
        if mention_role and report.overall_risk == OverallRisk.RED:
            content = f"<@&{mention_role}> High-risk applicant detected!"

        payload: dict[str, Any] = {
            "embeds": [embed],
        }
        if content:
            payload["content"] = content

        try:
            client = await self._get_client()
            response = await client.post(url, json=payload)
            return response.status_code in (200, 204)
        except Exception:
            return False

    async def send_batch_summary(
        self,
        reports: list[AnalysisReport],
        webhook_url: str | None = None,
    ) -> bool:
        """
        Send a summary of batch analysis results.

        Args:
            reports: List of analysis reports
            webhook_url: Override webhook URL

        Returns:
            True if sent successfully
        """
        url = webhook_url or self.webhook_url
        if not url or not reports:
            return False

        # Count by risk level
        red_count = sum(1 for r in reports if r.overall_risk == OverallRisk.RED)
        yellow_count = sum(1 for r in reports if r.overall_risk == OverallRisk.YELLOW)
        green_count = sum(1 for r in reports if r.overall_risk == OverallRisk.GREEN)

        # Determine overall color
        if red_count > 0:
            color = WebhookColor.RED
        elif yellow_count > 0:
            color = WebhookColor.YELLOW
        else:
            color = WebhookColor.GREEN

        # Build summary field
        summary_lines = [
            f"**Total Analyzed:** {len(reports)}",
            f"🔴 High Risk: {red_count}",
            f"🟡 Moderate Risk: {yellow_count}",
            f"🟢 Low Risk: {green_count}",
        ]

        fields = [
            {
                "name": "Summary",
                "value": "\n".join(summary_lines),
                "inline": False,
            }
        ]

        # List high-risk applicants
        high_risk = [r for r in reports if r.overall_risk == OverallRisk.RED]
        if high_risk:
            hr_text = "\n".join(
                f"• [{r.character_name}](https://zkillboard.com/character/{r.character_id}/)"
                for r in high_risk[:10]
            )
            fields.append(
                {
                    "name": "🚨 High Risk Applicants",
                    "value": hr_text,
                    "inline": False,
                }
            )

        embed = {
            "title": "Batch Analysis Complete",
            "color": color,
            "fields": fields,
            "footer": {"text": "EVE Sentinel"},
            "timestamp": datetime.now(UTC).isoformat(),
        }

        try:
            client = await self._get_client()
            response = await client.post(url, json={"embeds": [embed]})
            return response.status_code in (200, 204)
        except Exception:
            return False

    async def test_webhook(self, webhook_url: str | None = None) -> bool:
        """
        Send a test message to verify webhook configuration.

        Returns:
            True if webhook is working
        """
        url = webhook_url or self.webhook_url
        if not url:
            return False

        embed = {
            "title": "EVE Sentinel Webhook Test",
            "description": "Webhook is configured correctly!",
            "color": WebhookColor.GREEN,
            "footer": {"text": "EVE Sentinel"},
            "timestamp": datetime.now(UTC).isoformat(),
        }

        try:
            client = await self._get_client()
            response = await client.post(url, json={"embeds": [embed]})
            return response.status_code in (200, 204)
        except Exception:
            return False
