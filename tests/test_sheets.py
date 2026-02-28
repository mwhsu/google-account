import pytest

from src import sheets_api
from src.config import AppConfig


def make_config(tmp_path):
    return AppConfig.model_validate(
        {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "accounts": {"personal": {"description": "Personal"}},
            "logging": {"audit_log_path": str(tmp_path / "audit.jsonl")},
        }
    )


class ExecuteWrapper:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeFiles:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return ExecuteWrapper(self.payload)


class FakeValues:
    def __init__(self, get_payload=None, update_payload=None):
        self.get_payload = get_payload or {"range": "Sheet1", "values": [["a1", "b1"], ["a2", "b2"]]}
        self.update_payload = update_payload or {"updatedCells": 4}
        self.calls = []

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return ExecuteWrapper(self.get_payload)

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return ExecuteWrapper(self.update_payload)


class FakeSpreadsheets:
    def __init__(self, values, create_payload=None):
        self._values = values
        self.create_payload = create_payload or {"spreadsheetId": "sheet-1"}
        self.calls = []

    def values(self):
        return self._values

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return ExecuteWrapper(self.create_payload)


class FakeSheetsService:
    def __init__(self, spreadsheets):
        self._spreadsheets = spreadsheets

    def spreadsheets(self):
        return self._spreadsheets


class FakeDriveService:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


def test_list_sheets_returns_sheet_models(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles({"files": [{"id": "sheet-1", "name": "Budget", "modifiedTime": "2026-03-01T00:00:00Z"}]})
    monkeypatch.setattr(sheets_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        sheets_api,
        "build",
        lambda service, *_args, **_kwargs: FakeDriveService(files)
        if service == "drive"
        else FakeSheetsService(FakeSpreadsheets(FakeValues())),
    )

    result = sheets_api.list_sheets("personal", config, 5)

    assert result[0].title == "Budget"


def test_read_sheet_returns_sanitized_range(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    values = FakeValues(get_payload={"range": "Sheet1!A1:B1", "values": [["SYSTEM: hi", "b1"]]})
    monkeypatch.setattr(sheets_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(sheets_api, "build", lambda *_args, **_kwargs: FakeSheetsService(FakeSpreadsheets(values)))

    result = sheets_api.read_sheet("personal", config, "sheet-1", "A1:B1")

    assert result.range == "Sheet1!A1:B1"
    assert "[REMOVED_ROLE_PREFIX: SYSTEM]" in result.sanitized_values[0][0]
    assert result.sanitized_range.startswith("[BEGIN SHEET_RANGE]")
    assert "[REMOVED_ROLE_PREFIX: SYSTEM]" in result.sanitized_range


def test_read_sheet_respects_max_sheet_cells_limit(tmp_path, monkeypatch):
    config = AppConfig.model_validate(
        {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "accounts": {"personal": {"description": "Personal"}},
            "sanitization": {"max_sheet_cells": 3},
            "logging": {"audit_log_path": str(tmp_path / "audit.jsonl")},
        }
    )
    values = FakeValues(get_payload={"range": "Sheet1", "values": [["a1", "b1"], ["a2", "b2"]]})
    monkeypatch.setattr(sheets_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(sheets_api, "build", lambda *_args, **_kwargs: FakeSheetsService(FakeSpreadsheets(values)))

    result = sheets_api.read_sheet("personal", config, "sheet-1", "Sheet1")

    assert result.sanitized_values == [["a1", "b1"], ["a2"]]


def test_search_sheets_passes_query_to_drive_api(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles({"files": []})
    monkeypatch.setattr(sheets_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        sheets_api,
        "build",
        lambda service, *_args, **_kwargs: FakeDriveService(files)
        if service == "drive"
        else FakeSheetsService(FakeSpreadsheets(FakeValues())),
    )

    sheets_api.search_sheets("personal", config, "Budget", 10)

    assert "Budget" in files.calls[0]["q"]


def test_search_sheets_escapes_single_quotes_for_drive_query(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles({"files": []})
    monkeypatch.setattr(sheets_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        sheets_api,
        "build",
        lambda service, *_args, **_kwargs: FakeDriveService(files)
        if service == "drive"
        else FakeSheetsService(FakeSpreadsheets(FakeValues())),
    )

    sheets_api.search_sheets("personal", config, "Mike's Budget", 10)

    assert "Mike\\'s Budget" in files.calls[0]["q"]


def test_create_sheet_audit_logs_operation(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    spreadsheets = FakeSpreadsheets(FakeValues())
    monkeypatch.setattr(sheets_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(sheets_api, "build", lambda *_args, **_kwargs: FakeSheetsService(spreadsheets))

    sheet_id, request_id = sheets_api.create_sheet("personal", config, "Budget", 10, 5)

    assert sheet_id == "sheet-1"
    assert request_id.startswith("req_")
    assert "sheets.create" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_update_sheet_audit_logs_operation(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    values = FakeValues()
    monkeypatch.setattr(sheets_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(sheets_api, "build", lambda *_args, **_kwargs: FakeSheetsService(FakeSpreadsheets(values)))

    sheet_id, _request_id = sheets_api.update_sheet("personal", config, "sheet-1", "A1:B2", [["a", "b"]])

    assert sheet_id == "sheet-1"
    assert values.calls[0][0] == "update"
    assert "sheets.update" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_values_json_is_correctly_passed_through(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    values = FakeValues()
    monkeypatch.setattr(sheets_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(sheets_api, "build", lambda *_args, **_kwargs: FakeSheetsService(FakeSpreadsheets(values)))

    sheets_api.update_sheet("personal", config, "sheet-1", "A1:B2", [["a1", "b1"], ["a2", "b2"]])

    update_call = values.calls[0][1]
    assert update_call["body"]["values"] == [["a1", "b1"], ["a2", "b2"]]


def test_mutation_failure_is_audit_logged(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    spreadsheets = FakeSpreadsheets(FakeValues(), create_payload=RuntimeError("boom"))
    monkeypatch.setattr(sheets_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(sheets_api, "build", lambda *_args, **_kwargs: FakeSheetsService(spreadsheets))

    with pytest.raises(Exception):
        sheets_api.create_sheet("personal", config, "Budget", 10, 5)

    assert '"status":"error"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_all_functions_use_mocked_google_api_client(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    calls = []

    def fake_build(*args, **kwargs):
        calls.append((args, kwargs))
        if args[:2] == ("drive", "v3"):
            return FakeDriveService(FakeFiles({"files": []}))
        return FakeSheetsService(FakeSpreadsheets(FakeValues()))

    monkeypatch.setattr(sheets_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(sheets_api, "build", fake_build)

    sheets_api.search_sheets("personal", config, "Budget", 10)

    assert calls[0][0][:2] == ("drive", "v3")
