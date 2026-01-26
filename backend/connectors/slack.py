"""Slack webhook client for sending recruitment alerts."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.models.report import AnalysisReport, OverallRisk


class SlackColor:
    """Slack attachment colors for risk levels."""

    RED = "#E74C3C"  # High risk
    YELLOW = "#F39C12"  # Moderate risk
    GREEN = "#2ECC71"  # Low risk
    GRAY = "#95A5A6"  # Unknown


class SlackWebhook:
    """
    Client for sending recruitment alerts to Slack.

    Sends formatted Block Kit messages with risk assessment summaries.
    Includes retry logic with exponential backoff.
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        max_retries: int = 3,
        initial_delay: float = 1.0,
    ) -> None:
        self.webhook_url = webhook_url
        self.max_retries = max_retries
        self.initial_delay = initial_delay
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

    def _get_color(self, risk: OverallRisk) -> str:
        """Get attachment color for risk level."""
        colors = {
            OverallRisk.RED: SlackColor.RED,
            OverallRisk.YELLOW: SlackColor.YELLOW,
            OverallRisk.GREEN: SlackColor.GREEN,
            OverallRisk.UNKNOWN: SlackColor.GRAY,
        }
        return colors.get(risk, SlackColor.GRAY)

    def _get_risk_emoji(self, risk: OverallRisk) -> str:
        """Get emoji for risk level."""
        emojis = {
            OverallRisk.RED: ":red_circle:",
            OverallRisk.YELLOW: ":large_yellow_circle:",
            OverallRisk.GREEN: ":large_green_circle:",
            OverallRisk.UNKNOWN: ":white_circle:",
        }
        return emojis.get(risk, ":white_circle:")

    def _build_blocks(self, report: AnalysisReport) -> list[dict[str, Any]]:
        """Build Slack Block Kit blocks from analysis report."""
        risk_emoji = self._get_risk_emoji(report.overall_risk)
        zkill_url = f"https://zkillboard.com/character/{report.character_id}/"

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Recruitment Analysis: {report.character_name}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Risk Assessment:*\n{risk_emoji} *{report.overall_risk.value}* ({report.confidence:.0%} confidence)",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Flags:*\n:red_circle: {report.red_flag_count} | :large_yellow_circle: {report.yellow_flag_count} | :large_green_circle: {report.green_flag_count}",
                    },
                ],
            },
        ]

        # Add current corp/alliance if available
        if report.applicant_data:
            corp_info = report.applicant_data.corporation_name or "Unknown"
            if report.applicant_data.alliance_name:
                corp_info += f" [{report.applicant_data.alliance_name}]"
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Current Corporation:* {corp_info}",
                    },
                }
            )

        # Add red flags summary
        red_flags = [f for f in report.flags if f.severity.value == "RED"]
        if red_flags:
            flag_text = "\n".join(f"• {f.reason}" for f in red_flags[:5])
            if len(red_flags) > 5:
                flag_text += f"\n_...and {len(red_flags) - 5} more_"
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":rotating_light: *Red Flags:*\n{flag_text}",
                    },
                }
            )

        # Add yellow flags summary
        yellow_flags = [f for f in report.flags if f.severity.value == "YELLOW"]
        if yellow_flags:
            flag_text = "\n".join(f"• {f.reason}" for f in yellow_flags[:3])
            if len(yellow_flags) > 3:
                flag_text += f"\n_...and {len(yellow_flags) - 3} more_"
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":warning: *Yellow Flags:*\n{flag_text}",
                    },
                }
            )

        # Add recommendations
        if report.recommendations:
            rec_text = "\n".join(f"• {r}" for r in report.recommendations[:3])
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":clipboard: *Recommendations:*\n{rec_text}",
                    },
                }
            )

        # Add zkillboard link button
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View on zKillboard"},
                        "url": zkill_url,
                    }
                ],
            }
        )

        # Add footer
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"EVE Sentinel • Requested by {report.requested_by or 'Unknown'} • {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
                    }
                ],
            }
        )

        return blocks

    async def _send_with_retry(
        self,
        url: str,
        payload: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """
        Send request with exponential backoff retry.

        Returns:
            Tuple of (success, error_message)
        """
        client = await self._get_client()
        last_error: str | None = None

        for attempt in range(self.max_retries):
            try:
                response = await client.post(url, json=payload)

                if response.status_code == 200:
                    return True, None

                # Rate limited - respect Retry-After header
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "5"))
                    await asyncio.sleep(retry_after)
                    continue

                # Other error
                last_error = f"HTTP {response.status_code}: {response.text}"

            except httpx.TimeoutException:
                last_error = "Request timed out"
            except httpx.ConnectError:
                last_error = "Connection failed"
            except Exception as e:
                last_error = str(e)

            # Exponential backoff
            if attempt < self.max_retries - 1:
                delay = self.initial_delay * (2**attempt)
                await asyncio.sleep(delay)

        return False, last_error

    async def send_report(
        self,
        report: AnalysisReport,
        webhook_url: str | None = None,
        mention_channel: bool = False,
    ) -> tuple[bool, str | None]:
        """
        Send an analysis report to Slack.

        Args:
            report: The analysis report to send
            webhook_url: Override webhook URL (uses instance default if not provided)
            mention_channel: Whether to use @channel mention for high-risk

        Returns:
            Tuple of (success, error_message)
        """
        url = webhook_url or self.webhook_url
        if not url:
            return False, "No webhook URL configured"

        blocks = self._build_blocks(report)

        # Build payload
        payload: dict[str, Any] = {
            "blocks": blocks,
            "attachments": [
                {
                    "color": self._get_color(report.overall_risk),
                    "fallback": f"Recruitment Analysis: {report.character_name} - {report.overall_risk.value}",
                }
            ],
        }

        # Add @channel mention for high-risk
        if mention_channel and report.overall_risk == OverallRisk.RED:
            payload["text"] = "<!channel> High-risk applicant detected!"

        return await self._send_with_retry(url, payload)

    async def send_batch_summary(
        self,
        reports: list[AnalysisReport],
        webhook_url: str | None = None,
    ) -> tuple[bool, str | None]:
        """
        Send a summary of batch analysis results.

        Returns:
            Tuple of (success, error_message)
        """
        url = webhook_url or self.webhook_url
        if not url or not reports:
            return False, "No webhook URL or reports"

        # Count by risk level
        red_count = sum(1 for r in reports if r.overall_risk == OverallRisk.RED)
        yellow_count = sum(1 for r in reports if r.overall_risk == OverallRisk.YELLOW)
        green_count = sum(1 for r in reports if r.overall_risk == OverallRisk.GREEN)

        # Determine overall color
        if red_count > 0:
            color = SlackColor.RED
        elif yellow_count > 0:
            color = SlackColor.YELLOW
        else:
            color = SlackColor.GREEN

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Batch Analysis Complete",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Total Analyzed:* {len(reports)}"},
                    {
                        "type": "mrkdwn",
                        "text": f":red_circle: High Risk: {red_count}\n:large_yellow_circle: Moderate Risk: {yellow_count}\n:large_green_circle: Low Risk: {green_count}",
                    },
                ],
            },
        ]

        # List high-risk applicants
        high_risk = [r for r in reports if r.overall_risk == OverallRisk.RED]
        if high_risk:
            hr_text = "\n".join(
                f"• <https://zkillboard.com/character/{r.character_id}/|{r.character_name}>"
                for r in high_risk[:10]
            )
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":rotating_light: *High Risk Applicants:*\n{hr_text}",
                    },
                }
            )

        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"EVE Sentinel • {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
                    }
                ],
            }
        )

        payload = {
            "blocks": blocks,
            "attachments": [
                {"color": color, "fallback": f"Batch analysis: {len(reports)} reports"}
            ],
        }

        return await self._send_with_retry(url, payload)

    async def test_webhook(self, webhook_url: str | None = None) -> tuple[bool, str | None]:
        """
        Send a test message to verify webhook configuration.

        Returns:
            Tuple of (success, error_message)
        """
        url = webhook_url or self.webhook_url
        if not url:
            return False, "No webhook URL configured"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "EVE Sentinel Webhook Test",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":white_check_mark: Webhook is configured correctly!",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"EVE Sentinel • {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
                    }
                ],
            },
        ]

        payload = {
            "blocks": blocks,
            "attachments": [{"color": SlackColor.GREEN, "fallback": "Webhook test successful"}],
        }

        return await self._send_with_retry(url, payload)
