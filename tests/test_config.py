"""Settings behaviour: defaults and environment overrides."""

import pytest

from moex_spread_scanner.config import Settings


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests independent from a developer's local .env file."""
    monkeypatch.setenv("SCANNER_ENV_FILE", "/dev/null")


def test_defaults() -> None:
    settings = Settings()
    assert settings.iss_base_url == "https://iss.moex.com/iss"
    assert settings.history_days == 1095
    assert settings.z_entry_threshold == 2.0


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCANNER_HISTORY_DAYS", "30")
    settings = Settings()
    assert settings.history_days == 30


def test_invalid_value_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCANNER_HISTORY_DAYS", "not-a-number")
    with pytest.raises(ValueError):
        Settings()
