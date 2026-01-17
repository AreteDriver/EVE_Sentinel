"""Webhook management API endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from backend.config import settings
from backend.connectors.discord import DiscordWebhook
from backend.models.report import AnalysisReport, OverallRisk

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

# Shared webhook client
discord_client = DiscordWebhook(webhook_url=settings.discord_webhook_url)


class WebhookTestRequest(BaseModel):
    """Request to test a webhook URL."""

    url: HttpUrl


class WebhookTestResponse(BaseModel):
    """Response from webhook test."""

    success: bool
    message: str


class WebhookConfigResponse(BaseModel):
    """Current webhook configuration."""

    discord_configured: bool
    webhook_on_red: bool
    webhook_on_yellow: bool
    webhook_on_batch: bool
    alert_role_configured: bool


class SendReportRequest(BaseModel):
    """Request to send a report to webhook."""

    webhook_url: HttpUrl | None = None
    mention_role: str | None = None


@router.get("/config", response_model=WebhookConfigResponse)
async def get_webhook_config() -> WebhookConfigResponse:
    """Get current webhook configuration status."""
    return WebhookConfigResponse(
        discord_configured=settings.discord_webhook_url is not None,
        webhook_on_red=settings.webhook_on_red,
        webhook_on_yellow=settings.webhook_on_yellow,
        webhook_on_batch=settings.webhook_on_batch,
        alert_role_configured=settings.discord_alert_role_id is not None,
    )


@router.post("/test", response_model=WebhookTestResponse)
async def test_webhook(request: WebhookTestRequest) -> WebhookTestResponse:
    """
    Test a Discord webhook URL.

    Sends a test message to verify the webhook is configured correctly.
    """
    success = await discord_client.test_webhook(str(request.url))

    if success:
        return WebhookTestResponse(
            success=True,
            message="Webhook test successful! Check your Discord channel.",
        )
    else:
        return WebhookTestResponse(
            success=False,
            message="Webhook test failed. Check the URL and try again.",
        )


@router.post("/test-default", response_model=WebhookTestResponse)
async def test_default_webhook() -> WebhookTestResponse:
    """Test the default configured webhook."""
    if not settings.discord_webhook_url:
        raise HTTPException(
            status_code=400,
            detail="No default webhook URL configured. Set DISCORD_WEBHOOK_URL.",
        )

    success = await discord_client.test_webhook()

    if success:
        return WebhookTestResponse(
            success=True,
            message="Default webhook test successful!",
        )
    else:
        return WebhookTestResponse(
            success=False,
            message="Default webhook test failed.",
        )


async def send_report_webhook(
    report: AnalysisReport,
    webhook_url: str | None = None,
) -> bool:
    """
    Send a report to Discord based on configuration.

    Called automatically after analysis based on settings.

    Returns:
        True if sent (or not configured to send), False on failure
    """
    url = webhook_url or settings.discord_webhook_url
    if not url:
        return True  # Not configured, not an error

    # Check if we should send based on risk level
    should_send = False
    if report.overall_risk == OverallRisk.RED and settings.webhook_on_red:
        should_send = True
    elif report.overall_risk == OverallRisk.YELLOW and settings.webhook_on_yellow:
        should_send = True

    if not should_send:
        return True

    return await discord_client.send_report(
        report=report,
        webhook_url=url,
        mention_role=settings.discord_alert_role_id,
    )


async def send_batch_webhook(
    reports: list[AnalysisReport],
    webhook_url: str | None = None,
) -> bool:
    """
    Send batch summary to Discord.

    Returns:
        True if sent successfully
    """
    if not settings.webhook_on_batch:
        return True

    url = webhook_url or settings.discord_webhook_url
    if not url:
        return True

    return await discord_client.send_batch_summary(reports, url)
