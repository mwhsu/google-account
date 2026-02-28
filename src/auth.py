from pathlib import Path

import click

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:  # pragma: no cover - exercised only in dependency-light test envs
    class _MissingRequest:
        pass

    class _MissingCredentials:
        @staticmethod
        def from_authorized_user_file(*_args, **_kwargs):
            raise click.ClickException("google-auth is not installed")

    class _MissingInstalledAppFlow:
        @staticmethod
        def from_client_config(*_args, **_kwargs):
            raise click.ClickException("google-auth-oauthlib is not installed")

    Request = _MissingRequest
    Credentials = _MissingCredentials
    InstalledAppFlow = _MissingInstalledAppFlow

from src.config import AppConfig, get_account


SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _token_path(alias: str, config: AppConfig) -> Path:
    return Path(config.token_dir).expanduser() / f"{alias}.json"


def login(alias: str, config: AppConfig) -> None:
    get_account(alias, config)
    token_path = _token_path(alias, config)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        SCOPES,
    )
    credentials = flow.run_local_server(port=0)
    token_path.write_text(credentials.to_json(), encoding="utf-8")


def get_credentials(alias: str, config: AppConfig):
    get_account(alias, config)
    token_path = _token_path(alias, config)
    if not token_path.exists():
        raise click.ClickException(f"Account '{alias}' is not logged in")
    credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def list_accounts(config: AppConfig) -> list[dict]:
    accounts = []
    for alias, account_config in config.accounts.items():
        accounts.append(
            {
                "alias": alias,
                "description": account_config.description,
                "authenticated": _token_path(alias, config).exists(),
            }
        )
    return accounts


def remove(alias: str, config: AppConfig) -> None:
    get_account(alias, config)
    token_path = _token_path(alias, config)
    if token_path.exists():
        token_path.unlink()
