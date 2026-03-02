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


def test_sheets_read_plaintext_uses_wrapped_sanitized_range(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli_module, "load_config", lambda: object())
    monkeypatch.setattr(
        cli_module.sheets_api,
        "read_sheet",
        lambda *_args, **_kwargs: cli_module.SheetRange(
            spreadsheet_id="sheet-1",
            range="Sheet1!A1:B1",
            sanitized_range="[BEGIN SHEET_RANGE]\na1 | b1\n[END SHEET_RANGE]",
            sanitized_values=[["a1", "b1"]],
        ),
    )

    result = runner.invoke(cli_module.cli, ["sheets", "read", "--account", "personal", "sheet-1"])

    assert result.exit_code == 0
    assert "[BEGIN SHEET_RANGE]" in result.output


def test_sheets_update_rejects_non_tabular_json(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli_module, "load_config", lambda: object())

    result = runner.invoke(
        cli_module.cli,
        ["sheets", "update", "--account", "personal", "--range", "A1:B1", "--values", "{\"a\":1}", "sheet-1"],
    )

    assert result.exit_code != 0
    assert "--values must decode to a JSON array of rows" in result.output


def test_calendar_create_accepts_calendar_alias(monkeypatch):
    runner = CliRunner()
    seen = {}
    monkeypatch.setattr(cli_module, "load_config", lambda: object())

    def fake_create_event(account, config, title, start, end, description, location, calendar=None):
        seen.update(
            {
                "account": account,
                "config": config,
                "title": title,
                "calendar": calendar,
            }
        )
        return "evt-1", "req_123"

    monkeypatch.setattr(cli_module.calendar_api, "create_event", fake_create_event)

    result = runner.invoke(
        cli_module.cli,
        [
            "calendar",
            "create",
            "--account",
            "personal",
            "--calendar",
            "family",
            "--start",
            "2026-03-01T10:00:00Z",
            "--end",
            "2026-03-01T11:00:00Z",
            "Planning",
        ],
    )

    assert result.exit_code == 0
    assert seen["calendar"] == "family"


def test_free_busy_command_removed():
    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["calendar", "free-busy", "--help"])
    assert result.exit_code != 0


def test_drive_help_shows_subcommands():
    runner = CliRunner()

    result = runner.invoke(cli_module.cli, ["drive", "--help"])

    assert result.exit_code == 0
    for cmd in ["list", "search", "get", "download", "upload", "create-folder",
                "move", "rename", "trash", "delete", "share", "permissions"]:
        assert cmd in result.output


def test_help_shows_drive_group():
    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["--help"])
    assert "drive" in result.output


def test_docs_delete_delegates_to_drive_trash(monkeypatch):
    runner = CliRunner()
    seen = {}
    monkeypatch.setattr(cli_module, "load_config", lambda: object())
    monkeypatch.setattr(
        cli_module.drive_api,
        "trash_file",
        lambda account, config, file_id: (seen.update({"account": account, "file_id": file_id}) or ("doc-1", "req_123")),
    )

    result = runner.invoke(cli_module.cli, ["docs", "delete", "--account", "personal", "doc-1"])

    assert result.exit_code == 0
    assert seen["file_id"] == "doc-1"
    assert "trashed doc" in result.output


def test_sheets_delete_delegates_to_drive_trash(monkeypatch):
    runner = CliRunner()
    seen = {}
    monkeypatch.setattr(cli_module, "load_config", lambda: object())
    monkeypatch.setattr(
        cli_module.drive_api,
        "trash_file",
        lambda account, config, file_id: (seen.update({"account": account, "file_id": file_id}) or ("sheet-1", "req_456")),
    )

    result = runner.invoke(cli_module.cli, ["sheets", "delete", "--account", "personal", "sheet-1"])

    assert result.exit_code == 0
    assert seen["file_id"] == "sheet-1"
    assert "trashed sheet" in result.output


def test_docs_help_shows_delete():
    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["docs", "--help"])
    assert "delete" in result.output


def test_sheets_help_shows_delete():
    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["sheets", "--help"])
    assert "delete" in result.output


def test_contacts_help_shows_subcommands():
    runner = CliRunner()

    result = runner.invoke(cli_module.cli, ["contacts", "--help"])

    assert result.exit_code == 0
    for cmd in ["list", "search", "get", "create", "update", "delete"]:
        assert cmd in result.output


def test_help_shows_contacts_group():
    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["--help"])
    assert "contacts" in result.output


def test_gmail_help_shows_new_commands():
    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["gmail", "--help"])
    assert result.exit_code == 0
    for cmd in ["delete-draft", "archive", "label", "mark-read", "mark-unread"]:
        assert cmd in result.output


def test_gmail_label_requires_add_or_remove(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli_module, "load_config", lambda: object())

    result = runner.invoke(cli_module.cli, ["gmail", "label", "--account", "personal", "msg-1"])

    assert result.exit_code != 0
    assert "Specify at least one --add or --remove" in result.output
