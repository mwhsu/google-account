import json

import click
import pytest
from pydantic import ValidationError

from src.config import AppConfig, get_account, load_config


def write_config(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def base_config():
    return {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "accounts": {"personal": {"description": "Personal"}},
    }


def test_valid_config_loads_successfully(tmp_path, monkeypatch):
    write_config(tmp_path / "config.json", base_config())
    monkeypatch.chdir(tmp_path)

    config = load_config()

    assert isinstance(config, AppConfig)
    assert config.client_id == "client-id"


def test_missing_client_credentials_raise_validation_error():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"accounts": {}})


def test_empty_accounts_dict_is_valid():
    config = AppConfig.model_validate(
        {"client_id": "client-id", "client_secret": "client-secret", "accounts": {}}
    )

    assert config.accounts == {}


def test_get_account_raises_for_unknown_alias():
    config = AppConfig.model_validate(base_config())

    with pytest.raises(click.UsageError):
        get_account("missing", config)


def test_config_search_order_prefers_cwd(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config_dir = home / ".config" / "google-account"
    config_dir.mkdir(parents=True)
    write_config(config_dir / "config.json", {**base_config(), "client_id": "home-client"})
    write_config(tmp_path / "config.json", base_config())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(home))

    config = load_config()

    assert config.client_id == "client-id"


def test_config_search_order_uses_home_fallback(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config_dir = home / ".config" / "google-account"
    config_dir.mkdir(parents=True)
    write_config(config_dir / "config.json", base_config())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(home))

    config = load_config()

    assert config.client_secret == "client-secret"


def test_sanitization_defaults_are_applied(tmp_path, monkeypatch):
    write_config(tmp_path / "config.json", base_config())
    monkeypatch.chdir(tmp_path)

    config = load_config()

    assert config.sanitization.max_email_body_chars == 2000
    assert config.sanitization.strip_html is True
