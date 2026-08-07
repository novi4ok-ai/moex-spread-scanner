"""Application settings: single source of truth, env-overridable."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable via environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SCANNER_",
        extra="ignore",
    )

    iss_base_url: str = "https://iss.moex.com/iss"
    history_days: int = 1095
    z_entry_threshold: float = 2.0
    request_pause_seconds: float = 0.2


def get_settings() -> Settings:
    """Build settings from environment (and .env if present)."""
    return Settings()
