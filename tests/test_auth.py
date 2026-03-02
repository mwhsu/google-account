import json

import click
import pytest

from src import auth
from src.config import AppConfig


def make_config(tmp_path):
    return AppConfig.model_validate(
        {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "accounts": {"personal": {"description": "Personal"}},
            "token_dir": str(tmp_path / "tokens"),
        }
    )


class FakeCredentials:
    def __init__(self, expired=False, refresh_token="refresh-token", scopes=None):
        self.expired = expired
        self.refresh_token = refresh_token
        self.refreshed = False
        self.scopes = scopes if scopes is not None else set(auth.SCOPES)

    def to_json(self):
        return json.dumps({"token": "abc"})

    def refresh(self, _request):
        self.refreshed = True
        self.expired = False


class FakeFlow:
    def __init__(self, credentials):
        self._credentials = credentials

    def run_local_server(self, port):
        assert port == 0
        return self._credentials


def test_login_creates_token_file(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    creds = FakeCredentials()
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config", lambda *_args, **_kwargs: FakeFlow(creds))

    auth.login("personal", config)

    assert (tmp_path / "tokens" / "personal.json").exists()


def test_get_credentials_loads_existing_token(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    token_path = tmp_path / "tokens" / "personal.json"
    token_path.parent.mkdir()
    token_path.write_text("{}", encoding="utf-8")
    creds = FakeCredentials()
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", lambda *_args, **_kwargs: creds)

    result = auth.get_credentials("personal", config)

    assert result is creds


def test_get_credentials_raises_when_not_logged_in(tmp_path):
    config = make_config(tmp_path)

    with pytest.raises(click.ClickException):
        auth.get_credentials("personal", config)


def test_list_accounts_shows_auth_status(tmp_path):
    config = make_config(tmp_path)
    token_path = tmp_path / "tokens" / "personal.json"
    token_path.parent.mkdir()
    token_path.write_text("{}", encoding="utf-8")

    accounts = auth.list_accounts(config)

    assert accounts == [{"alias": "personal", "description": "Personal", "authenticated": True}]


def test_remove_deletes_token_file(tmp_path):
    config = make_config(tmp_path)
    token_path = tmp_path / "tokens" / "personal.json"
    token_path.parent.mkdir()
    token_path.write_text("{}", encoding="utf-8")

    auth.remove("personal", config)

    assert not token_path.exists()


def test_token_refresh_is_attempted_for_expired_tokens(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    token_path = tmp_path / "tokens" / "personal.json"
    token_path.parent.mkdir()
    token_path.write_text("{}", encoding="utf-8")
    creds = FakeCredentials(expired=True)
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", lambda *_args, **_kwargs: creds)

    auth.get_credentials("personal", config)

    assert creds.refreshed is True


def test_scopes_include_drive_for_full_file_access():
    assert "https://www.googleapis.com/auth/drive" in auth.SCOPES
    assert "https://www.googleapis.com/auth/gmail.modify" in auth.SCOPES
    assert "https://www.googleapis.com/auth/contacts" in auth.SCOPES
