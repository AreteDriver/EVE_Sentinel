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

    # Discord webhooks
    discord_webhook_url: str | None = None
    discord_alert_role_id: str | None = None  # Role to mention for high-risk

    # Webhook behavior
    webhook_on_red: bool = True  # Send webhook for RED risk
    webhook_on_yellow: bool = False  # Send webhook for YELLOW risk
    webhook_on_batch: bool = True  # Send summary after batch analysis

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
