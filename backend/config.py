"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application settings
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    session_secret_key: str = "change-me-in-production-use-secrets-token-hex-32"

    # Discord webhooks
    discord_webhook_url: str | None = None
    discord_alert_role_id: str | None = None  # Role to mention for high-risk

    # Slack webhooks
    slack_webhook_url: str | None = None
    slack_mention_channel: bool = True  # Use @channel for high-risk alerts

    # Webhook behavior
    webhook_on_red: bool = True  # Send webhook for RED risk
    webhook_on_yellow: bool = False  # Send webhook for YELLOW risk
    webhook_on_batch: bool = True  # Send summary after batch analysis
    webhook_max_retries: int = 3  # Max retry attempts
    webhook_retry_delay: float = 1.0  # Initial retry delay in seconds

    # ESI configuration (for future authenticated endpoints)
    esi_client_id: str | None = None
    esi_secret_key: str | None = None
    esi_callback_url: str = "http://localhost:8000/callback"

    # Hostile entities (comma-separated IDs)
    hostile_corps: str = ""  # e.g., "667531913,98000001"
    hostile_alliances: str = ""  # e.g., "1354830081,99000001"

    # Database (for future persistence)
    database_url: str = "sqlite:///./sentinel.db"

    # Auth Bridge (Alliance Auth or SeAT integration)
    auth_system: str | None = None  # "alliance_auth" or "seat"
    auth_bridge_url: str | None = None  # e.g., "https://auth.youralliance.com"
    auth_bridge_token: str | None = None  # API token for auth system

    # API Authentication
    require_api_key: bool = False  # Set to True to require API key for all requests
    api_keys: str = ""  # Comma-separated list of valid API keys

    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_default: str = "100/minute"

    # Redis Caching
    redis_enabled: bool = False  # Disabled by default, enable when Redis is available
    redis_url: str = "redis://localhost:6379"
    redis_prefix: str = "sentinel:"

    # Background Scheduler
    scheduler_enabled: bool = False  # Disabled by default, enable in production
    scheduler_interval_minutes: int = 60  # Run reanalysis every N minutes
    scheduler_max_per_run: int = 10  # Max characters to analyze per run

    # Base URL (for links in notifications)
    base_url: str | None = None

    # Discord Bot
    discord_bot_token: str | None = None  # Bot token from Discord Developer Portal
    discord_guild_ids: str = ""  # Comma-separated guild IDs for slash commands (optional)
    discord_admin_role_id: str | None = None  # Role ID that can use admin commands

    def get_discord_guild_ids(self) -> list[int]:
        """Parse Discord guild IDs from comma-separated string."""
        if not self.discord_guild_ids:
            return []
        return [int(x.strip()) for x in self.discord_guild_ids.split(",") if x.strip()]

    def get_api_keys(self) -> set[str]:
        """Parse API keys from comma-separated string."""
        if not self.api_keys:
            return set()
        return {x.strip() for x in self.api_keys.split(",") if x.strip()}

    def get_hostile_corp_ids(self) -> set[int]:
        """Parse hostile corp IDs from comma-separated string."""
        if not self.hostile_corps:
            return set()
        return {int(x.strip()) for x in self.hostile_corps.split(",") if x.strip()}

    def get_hostile_alliance_ids(self) -> set[int]:
        """Parse hostile alliance IDs from comma-separated string."""
        if not self.hostile_alliances:
            return set()
        return {int(x.strip()) for x in self.hostile_alliances.split(",") if x.strip()}

    def get_cors_origins(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        if not self.cors_origins:
            return []
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


# Global settings instance
settings = Settings()
