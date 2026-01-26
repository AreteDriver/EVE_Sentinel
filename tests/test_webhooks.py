"""Tests for Discord webhook functionality."""

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from backend.connectors.discord import DiscordWebhook, WebhookColor
from backend.main import app
from backend.models.flags import FlagCategory, FlagSeverity, RiskFlag
from backend.models.report import AnalysisReport, OverallRisk


@pytest.fixture
def mock_report() -> AnalysisReport:
    """Create a mock analysis report for testing."""
    return AnalysisReport(
        character_id=12345678,
        character_name="Test Pilot",
        overall_risk=OverallRisk.RED,
        confidence=0.85,
        flags=[
            RiskFlag(
                severity=FlagSeverity.RED,
                category=FlagCategory.CORP_HISTORY,
                code="KNOWN_SPY_CORP",
                reason="Known hostile corporation",
            ),
            RiskFlag(
                severity=FlagSeverity.YELLOW,
                category=FlagCategory.KILLBOARD,
                code="LOW_ACTIVITY",
                reason="Low recent activity",
            ),
        ],
        recommendations=["Reject application", "Review corp history"],
        analyzers_run=["CorpHistoryAnalyzer", "KillboardAnalyzer"],
        requested_by="recruiter@corp",
        red_flag_count=1,
        yellow_flag_count=1,
    )


@pytest.fixture
def green_report() -> AnalysisReport:
    """Create a green (low risk) report."""
    return AnalysisReport(
        character_id=87654321,
        character_name="Safe Pilot",
        overall_risk=OverallRisk.GREEN,
        confidence=0.90,
        flags=[
            RiskFlag(
                severity=FlagSeverity.GREEN,
                category=FlagCategory.CORP_HISTORY,
                code="CLEAN_HISTORY",
                reason="Clean history",
            ),
        ],
        recommendations=["Standard onboarding"],
        analyzers_run=["CorpHistoryAnalyzer"],
        requested_by="recruiter@corp",
        green_flag_count=1,
    )


class TestWebhookColor:
    """Tests for webhook color enum."""

    def test_red_color_value(self):
        """Test RED color has correct hex value."""
        assert WebhookColor.RED == 0xE74C3C

    def test_yellow_color_value(self):
        """Test YELLOW color has correct hex value."""
        assert WebhookColor.YELLOW == 0xF39C12

    def test_green_color_value(self):
        """Test GREEN color has correct hex value."""
        assert WebhookColor.GREEN == 0x2ECC71


class TestDiscordWebhook:
    """Tests for DiscordWebhook client."""

    @pytest.fixture
    def webhook_client(self):
        """Create webhook client with test URL."""
        return DiscordWebhook(webhook_url="https://discord.com/api/webhooks/test/token")

    def test_get_color_red(self, webhook_client):
        """Test getting color for RED risk."""
        color = webhook_client._get_color(OverallRisk.RED)
        assert color == WebhookColor.RED

    def test_get_color_yellow(self, webhook_client):
        """Test getting color for YELLOW risk."""
        color = webhook_client._get_color(OverallRisk.YELLOW)
        assert color == WebhookColor.YELLOW

    def test_get_color_green(self, webhook_client):
        """Test getting color for GREEN risk."""
        color = webhook_client._get_color(OverallRisk.GREEN)
        assert color == WebhookColor.GREEN

    def test_get_color_unknown(self, webhook_client):
        """Test getting color for UNKNOWN risk."""
        color = webhook_client._get_color(OverallRisk.UNKNOWN)
        assert color == WebhookColor.GRAY

    def test_get_risk_emoji_red(self, webhook_client):
        """Test emoji for RED risk."""
        emoji = webhook_client._get_risk_emoji(OverallRisk.RED)
        assert emoji == "🔴"

    def test_get_risk_emoji_green(self, webhook_client):
        """Test emoji for GREEN risk."""
        emoji = webhook_client._get_risk_emoji(OverallRisk.GREEN)
        assert emoji == "🟢"

    def test_build_embed_contains_title(self, webhook_client, mock_report):
        """Test embed has correct title."""
        embed = webhook_client._build_embed(mock_report)
        assert embed["title"] == "Recruitment Analysis: Test Pilot"

    def test_build_embed_contains_url(self, webhook_client, mock_report):
        """Test embed has zkillboard link."""
        embed = webhook_client._build_embed(mock_report)
        assert embed["url"] == "https://zkillboard.com/character/12345678/"

    def test_build_embed_has_color(self, webhook_client, mock_report):
        """Test embed has correct color for risk level."""
        embed = webhook_client._build_embed(mock_report)
        assert embed["color"] == WebhookColor.RED

    def test_build_embed_has_fields(self, webhook_client, mock_report):
        """Test embed has expected fields."""
        embed = webhook_client._build_embed(mock_report)
        field_names = [f["name"] for f in embed["fields"]]
        assert "Risk Assessment" in field_names
        assert "Flags" in field_names

    def test_build_embed_includes_red_flags(self, webhook_client, mock_report):
        """Test embed includes red flags section."""
        embed = webhook_client._build_embed(mock_report)
        field_names = [f["name"] for f in embed["fields"]]
        assert "🚨 Red Flags" in field_names

    def test_build_embed_includes_yellow_flags(self, webhook_client, mock_report):
        """Test embed includes yellow flags section."""
        embed = webhook_client._build_embed(mock_report)
        field_names = [f["name"] for f in embed["fields"]]
        assert "⚠️ Yellow Flags" in field_names

    def test_build_embed_includes_recommendations(self, webhook_client, mock_report):
        """Test embed includes recommendations."""
        embed = webhook_client._build_embed(mock_report)
        field_names = [f["name"] for f in embed["fields"]]
        assert "📋 Recommendations" in field_names

    def test_build_embed_has_footer(self, webhook_client, mock_report):
        """Test embed has footer with requester."""
        embed = webhook_client._build_embed(mock_report)
        assert "recruiter@corp" in embed["footer"]["text"]

    def test_build_embed_has_timestamp(self, webhook_client, mock_report):
        """Test embed has timestamp."""
        embed = webhook_client._build_embed(mock_report)
        assert "timestamp" in embed

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_report_success(self, webhook_client, mock_report):
        """Test successfully sending a report."""
        route = respx.post("https://discord.com/api/webhooks/test/token").mock(
            return_value=Response(204)
        )

        success, error = await webhook_client.send_report(mock_report)

        assert success is True
        assert error is None
        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_report_failure(self, webhook_client, mock_report):
        """Test handling failed webhook send."""
        respx.post("https://discord.com/api/webhooks/test/token").mock(return_value=Response(400))

        success, error = await webhook_client.send_report(mock_report)

        assert success is False
        assert error is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_report_with_role_mention(self, webhook_client, mock_report):
        """Test that RED risk reports include role mention."""
        route = respx.post("https://discord.com/api/webhooks/test/token").mock(
            return_value=Response(204)
        )

        await webhook_client.send_report(mock_report, mention_role="123456789")

        # Check that the payload included content with role mention
        request = route.calls[0].request
        import json

        body = json.loads(request.content)
        assert "content" in body
        assert "<@&123456789>" in body["content"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_report_no_mention_for_green(self, webhook_client, green_report):
        """Test that GREEN risk reports don't include role mention."""
        route = respx.post("https://discord.com/api/webhooks/test/token").mock(
            return_value=Response(204)
        )

        await webhook_client.send_report(green_report, mention_role="123456789")

        request = route.calls[0].request
        import json

        body = json.loads(request.content)
        assert "content" not in body

    @pytest.mark.asyncio
    async def test_send_report_no_url_returns_false(self, mock_report):
        """Test that missing URL returns False with error message."""
        client = DiscordWebhook()  # No URL
        success, error = await client.send_report(mock_report)
        assert success is False
        assert error == "No webhook URL configured"

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_batch_summary_success(self, webhook_client, mock_report, green_report):
        """Test sending batch summary."""
        route = respx.post("https://discord.com/api/webhooks/test/token").mock(
            return_value=Response(204)
        )

        success, error = await webhook_client.send_batch_summary([mock_report, green_report])

        assert success is True
        assert error is None
        assert route.called

    @pytest.mark.asyncio
    async def test_send_batch_summary_empty_list(self, webhook_client):
        """Test batch summary with empty list returns False with error."""
        success, error = await webhook_client.send_batch_summary([])
        assert success is False
        assert "No webhook URL or reports" in error

    @pytest.mark.asyncio
    @respx.mock
    async def test_test_webhook_success(self, webhook_client):
        """Test webhook test succeeds."""
        respx.post("https://discord.com/api/webhooks/test/token").mock(return_value=Response(200))

        success, error = await webhook_client.test_webhook()

        assert success is True
        assert error is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_test_webhook_failure(self, webhook_client):
        """Test webhook test failure."""
        respx.post("https://discord.com/api/webhooks/test/token").mock(return_value=Response(401))

        success, error = await webhook_client.test_webhook()

        assert success is False
        assert error is not None


class TestWebhookAPIEndpoints:
    """Tests for webhook API endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_get_webhook_config(self, client):
        """Test getting webhook configuration."""
        response = client.get("/api/v1/webhooks/config")

        assert response.status_code == 200
        data = response.json()
        assert "discord_configured" in data
        assert "slack_configured" in data
        assert "webhook_on_red" in data
        assert "webhook_on_yellow" in data
        assert "webhook_on_batch" in data
        assert "discord_alert_role_configured" in data
        assert "slack_mention_channel" in data
        assert "max_retries" in data

    def test_webhook_config_defaults(self, client):
        """Test default webhook configuration values."""
        response = client.get("/api/v1/webhooks/config")

        data = response.json()
        # Default values from config.py
        assert data["webhook_on_red"] is True
        assert data["webhook_on_yellow"] is False
        assert data["webhook_on_batch"] is True

    @respx.mock
    def test_test_webhook_endpoint_success(self, client):
        """Test the webhook test endpoint."""
        respx.post("https://discord.com/api/webhooks/test/token").mock(return_value=Response(204))

        response = client.post(
            "/api/v1/webhooks/test",
            json={"url": "https://discord.com/api/webhooks/test/token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "successful" in data["message"].lower()

    @respx.mock
    def test_test_webhook_endpoint_failure(self, client):
        """Test webhook test endpoint when webhook fails."""
        respx.post("https://discord.com/api/webhooks/bad/url").mock(return_value=Response(400))

        response = client.post(
            "/api/v1/webhooks/test",
            json={"url": "https://discord.com/api/webhooks/bad/url"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "failed" in data["message"].lower()

    def test_test_webhook_invalid_url(self, client):
        """Test webhook test with invalid URL."""
        response = client.post(
            "/api/v1/webhooks/test",
            json={"url": "not-a-valid-url"},
        )

        # Pydantic validation should fail
        assert response.status_code == 422

    def test_test_default_webhook_no_config(self, client):
        """Test default webhook test when not configured."""
        response = client.post("/api/v1/webhooks/test-default")

        # Should return 400 since no webhook is configured by default
        assert response.status_code == 400
        assert "no default discord webhook" in response.json()["detail"].lower()
