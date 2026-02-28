import json

from click.testing import CliRunner

from src import cli as cli_module
from src.models import EmailMessage


def test_google_help_shows_command_groups():
    runner = CliRunner()

    result = runner.invoke(cli_module.cli, ["--help"])

    assert result.exit_code == 0
    assert "auth" in result.output
    assert "gmail" in result.output
    assert "calendar" in result.output
    assert "docs" in result.output
    assert "sheets" in result.output


def test_gmail_inbox_without_account_shows_error():
    runner = CliRunner()

    result = runner.invoke(cli_module.cli, ["gmail", "inbox"])

    assert result.exit_code != 0
    assert "--account" in result.output


def test_auth_list_works_without_account(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli_module, "load_config", lambda: object())
    monkeypatch.setattr(cli_module.auth_api, "list_accounts", lambda _config: [{"alias": "personal"}])

    result = runner.invoke(cli_module.cli, ["auth", "list"])

    assert result.exit_code == 0
    assert json.loads(result.output) == [{"alias": "personal"}]


def test_json_flag_produces_valid_json(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli_module, "load_config", lambda: object())
    monkeypatch.setattr(
        cli_module.gmail,
        "get_inbox",
        lambda *_args, **_kwargs: [
            EmailMessage(
                id="msg-1",
                thread_id="thread-1",
                subject="Hello",
                sender="a@example.com",
                to="b@example.com",
                date="today",
                snippet="snippet",
                sanitized_body="[BEGIN EMAIL_BODY]\nhello\n[END EMAIL_BODY]",
                labels=["INBOX"],
            )
        ],
    )

    result = runner.invoke(cli_module.cli, ["gmail", "inbox", "--account", "personal", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["id"] == "msg-1"


def test_cli_loads_config_and_passes_it_through(monkeypatch):
    runner = CliRunner()
    config = object()
    seen = {}
    monkeypatch.setattr(cli_module, "load_config", lambda: config)

    def fake_get_labels(account, loaded_config):
        seen["account"] = account
        seen["config"] = loaded_config
        return []

    monkeypatch.setattr(cli_module.gmail, "get_labels", fake_get_labels)

    result = runner.invoke(cli_module.cli, ["gmail", "labels", "--account", "personal", "--json"])

    assert result.exit_code == 0
    assert seen == {"account": "personal", "config": config}


def test_docs_help_shows_subcommands():
    runner = CliRunner()

    result = runner.invoke(cli_module.cli, ["docs", "--help"])

    assert result.exit_code == 0
    assert "list" in result.output
    assert "read" in result.output
    assert "search" in result.output
    assert "create" in result.output
    assert "update" in result.output


def test_sheets_help_shows_subcommands():
    runner = CliRunner()

    result = runner.invoke(cli_module.cli, ["sheets", "--help"])

    assert result.exit_code == 0
    assert "list" in result.output
    assert "read" in result.output
    assert "search" in result.output
    assert "create" in result.output
    assert "update" in result.output


def test_docs_update_requires_exactly_one_mode(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli_module, "load_config", lambda: object())

    result = runner.invoke(cli_module.cli, ["docs", "update", "--account", "personal", "doc-1"])

    assert result.exit_code != 0
    assert "Specify exactly one of --replace or --append" in result.output
