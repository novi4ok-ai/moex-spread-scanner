"""MOEX spread scanner package."""

from moex_spread_scanner.config import get_settings


def main() -> None:
    settings = get_settings()
    print("moex-spread-scanner settings:")
    for key, value in settings.model_dump().items():
        print(f"  {key} = {value}")
