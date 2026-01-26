"""Webhook management API endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from backend.config import settings
from backend.connectors.discord import DiscordWebhook
from backend.connectors.slack import SlackWebhook
from backend.models.report import AnalysisReport, OverallRisk

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

# Shared webhook clients with retry configuration
discord_client = DiscordWebhook(
    webhook_url=settings.discord_webhook_url,
    max_retries=settings.webhook_max_retries,
    initial_delay=settings.webhook_retry_delay,
)

slack_client = SlackWebhook(
    webhook_url=settings.slack_webhook_url,
    max_retries=settings.webhook_max_retries,
    initial_delay=settings.webhook_retry_delay,
)


class WebhookTestRequest(BaseModel):
    """Request to test a webhook URL."""

    url: HttpUrl
    webhook_type: str = "discord"  # discord or slack


class WebhookTestResponse(BaseModel):
    """Response from webhook test."""

    success: bool
    message: str
    webhook_type: str
    error: str | None = None


class WebhookConfigResponse(BaseModel):
    """Current webhook configuration."""

    discord_configured: bool
    slack_configured: bool
    webhook_on_red: bool
    webhook_on_yellow: bool
    webhook_on_batch: bool
    discord_alert_role_configured: bool
    slack_mention_channel: bool
    max_retries: int


class SendReportRequest(BaseModel):
    """Request to send a report to webhook."""

    webhook_url: HttpUrl | None = None
    webhook_type: str = "discord"  # discord or slack
    mention_role: str | None = None
    mention_channel: bool = False


class WebhookStatusResponse(BaseModel):
    """Status of webhook delivery."""

    discord_sent: bool
    discord_error: str | None = None
    slack_sent: bool
    slack_error: str | None = None


@router.get("/config", response_model=WebhookConfigResponse)
async def get_webhook_config() -> WebhookConfigResponse:
    """Get current webhook configuration status."""
    return WebhookConfigResponse(
        discord_configured=settings.discord_webhook_url is not None,
        slack_configured=settings.slack_webhook_url is not None,
        webhook_on_red=settings.webhook_on_red,
        webhook_on_yellow=settings.webhook_on_yellow,
        webhook_on_batch=settings.webhook_on_batch,
        discord_alert_role_configured=settings.discord_alert_role_id is not None,
        slack_mention_channel=settings.slack_mention_channel,
        max_retries=settings.webhook_max_retries,
    )


@router.post("/test", response_model=WebhookTestResponse)
async def test_webhook(request: WebhookTestRequest) -> WebhookTestResponse:
    """
    Test a webhook URL.

    Sends a test message to verify the webhook is configured correctly.
    Supports both Discord and Slack webhooks.
    """
    if request.webhook_type == "slack":
        success, error = await slack_client.test_webhook(str(request.url))
        return WebhookTestResponse(
            success=success,
            message="Webhook test successful! Check your Slack channel."
            if success
            else "Webhook test failed.",
            webhook_type="slack",
            error=error,
        )
    else:
        success, error = await discord_client.test_webhook(str(request.url))
        return WebhookTestResponse(
            success=success,
            message="Webhook test successful! Check your Discord channel."
            if success
            else "Webhook test failed.",
            webhook_type="discord",
            error=error,
        )


@router.post("/test-discord", response_model=WebhookTestResponse)
async def test_default_discord_webhook() -> WebhookTestResponse:
    """Test the default configured Discord webhook."""
    if not settings.discord_webhook_url:
        raise HTTPException(
            status_code=400,
            detail="No default Discord webhook URL configured. Set DISCORD_WEBHOOK_URL.",
        )

    success, error = await discord_client.test_webhook()

    return WebhookTestResponse(
        success=success,
        message="Discord webhook test successful!" if success else "Discord webhook test failed.",
        webhook_type="discord",
        error=error,
    )


@router.post("/test-slack", response_model=WebhookTestResponse)
async def test_default_slack_webhook() -> WebhookTestResponse:
    """Test the default configured Slack webhook."""
    if not settings.slack_webhook_url:
        raise HTTPException(
            status_code=400,
            detail="No default Slack webhook URL configured. Set SLACK_WEBHOOK_URL.",
        )

    success, error = await slack_client.test_webhook()

    return WebhookTestResponse(
        success=success,
        message="Slack webhook test successful!" if success else "Slack webhook test failed.",
        webhook_type="slack",
        error=error,
    )


# Keep old endpoint for backwards compatibility
@router.post("/test-default", response_model=WebhookTestResponse)
async def test_default_webhook() -> WebhookTestResponse:
    """Test the default configured Discord webhook (backwards compatibility)."""
    return await test_default_discord_webhook()


async def send_report_webhook(
    report: AnalysisReport,
    webhook_url: str | None = None,
) -> WebhookStatusResponse:
    """
    Send a report to all configured webhooks based on configuration.

    Called automatically after analysis based on settings.

    Returns:
        WebhookStatusResponse with delivery status for each webhook type
    """
    discord_sent = False
    discord_error: str | None = None
    slack_sent = False
    slack_error: str | None = None

    # Check if we should send based on risk level
    should_send = False
    if report.overall_risk == OverallRisk.RED and settings.webhook_on_red:
        should_send = True
    elif report.overall_risk == OverallRisk.YELLOW and settings.webhook_on_yellow:
        should_send = True

    if not should_send:
        return WebhookStatusResponse(
            discord_sent=True,
            slack_sent=True,
        )

    # Send to Discord
    discord_url = webhook_url or settings.discord_webhook_url
    if discord_url:
        discord_sent, discord_error = await discord_client.send_report(
            report=report,
            webhook_url=discord_url,
            mention_role=settings.discord_alert_role_id,
        )

    # Send to Slack
    slack_url = settings.slack_webhook_url
    if slack_url and not webhook_url:  # Only use default Slack if no override provided
        slack_sent, slack_error = await slack_client.send_report(
            report=report,
            webhook_url=slack_url,
            mention_channel=settings.slack_mention_channel,
        )

    return WebhookStatusResponse(
        discord_sent=discord_sent,
        discord_error=discord_error,
        slack_sent=slack_sent,
        slack_error=slack_error,
    )


async def send_batch_webhook(
    reports: list[AnalysisReport],
    webhook_url: str | None = None,
) -> WebhookStatusResponse:
    """
    Send batch summary to all configured webhooks.

    Returns:
        WebhookStatusResponse with delivery status for each webhook type
    """
    discord_sent = False
    discord_error: str | None = None
    slack_sent = False
    slack_error: str | None = None

    if not settings.webhook_on_batch:
        return WebhookStatusResponse(
            discord_sent=True,
            slack_sent=True,
        )

    # Send to Discord
    discord_url = webhook_url or settings.discord_webhook_url
    if discord_url:
        discord_sent, discord_error = await discord_client.send_batch_summary(reports, discord_url)

    # Send to Slack
    slack_url = settings.slack_webhook_url
    if slack_url and not webhook_url:
        slack_sent, slack_error = await slack_client.send_batch_summary(reports, slack_url)

    return WebhookStatusResponse(
        discord_sent=discord_sent,
        discord_error=discord_error,
        slack_sent=slack_sent,
        slack_error=slack_error,
    )


@router.post("/send-report/{report_id}", response_model=WebhookStatusResponse)
async def manually_send_report_webhook(
    report_id: str,
    request: SendReportRequest | None = None,
) -> WebhookStatusResponse:
    """
    Manually send a report to webhooks.

    Allows sending a report to a specific webhook URL,
    overriding the default configuration.
    """
    from uuid import UUID

    from backend.database import ReportRepository, get_session

    async with get_session() as session:
        repo = ReportRepository(session)
        report = await repo.get_by_id(UUID(report_id))

        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        if request and request.webhook_url:
            if request.webhook_type == "slack":
                success, error = await slack_client.send_report(
                    report=report,
                    webhook_url=str(request.webhook_url),
                    mention_channel=request.mention_channel,
                )
                return WebhookStatusResponse(
                    discord_sent=False,
                    slack_sent=success,
                    slack_error=error,
                )
            else:
                success, error = await discord_client.send_report(
                    report=report,
                    webhook_url=str(request.webhook_url),
                    mention_role=request.mention_role,
                )
                return WebhookStatusResponse(
                    discord_sent=success,
                    discord_error=error,
                    slack_sent=False,
                )
        else:
            # Send to all configured webhooks
            return await send_report_webhook(report)
