import json
from pathlib import Path

import click
from pydantic import BaseModel


class SanitizationConfig(BaseModel):
    max_email_body_chars: int = 2000
    max_doc_chars: int = 8000
    max_sheet_cells: int = 200
    max_calendar_description_chars: int = 1000
    strip_html: bool = True
    neutralize_injections: bool = True


class LoggingConfig(BaseModel):
    audit_log_path: str = "~/.config/google-account/audit.jsonl"


class AccountConfig(BaseModel):
    description: str = ""
    calendar_id: str | None = None


class AppConfig(BaseModel):
    client_id: str
    client_secret: str
    accounts: dict[str, AccountConfig]
    calendars: dict[str, str] = {}
    sanitization: SanitizationConfig = SanitizationConfig()
    logging: LoggingConfig = LoggingConfig()
    token_dir: str = "~/.config/google-account/tokens"


def _config_candidates() -> list[Path]:
    return [
        Path.cwd() / "config.json",
        Path("~/.config/google-account/config.json").expanduser(),
    ]


def load_config() -> AppConfig:
    for path in _config_candidates():
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                return AppConfig.model_validate(json.load(handle))
    raise click.ClickException("config.json not found in cwd or ~/.config/google-account/")


def get_account(alias: str, config: AppConfig | None = None) -> AccountConfig:
    active_config = config or load_config()
    if alias not in active_config.accounts:
        raise click.UsageError(f"Unknown account alias: {alias}")
    return active_config.accounts[alias]


def get_calendar_id(alias: str | None, config: AppConfig | None = None) -> str:
    if alias in (None, "", "primary"):
        return "primary"
    active_config = config or load_config()
    if alias not in active_config.calendars:
        raise click.UsageError(f"Unknown calendar alias: {alias}")
    return active_config.calendars[alias]
