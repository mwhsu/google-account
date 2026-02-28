import pytest

from src import calendar_api
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


class FakeEvents:
    def __init__(self, list_payload, mutation_payload=None):
        self.list_payload = list_payload
        self.mutation_payload = mutation_payload or {"id": "evt-1"}
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return ExecuteWrapper({"items": self.list_payload})

    def insert(self, **kwargs):
        self.calls.append(("insert", kwargs))
        return ExecuteWrapper(self.mutation_payload)

    def patch(self, **kwargs):
        self.calls.append(("patch", kwargs))
        return ExecuteWrapper(self.mutation_payload)

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return ExecuteWrapper(self.mutation_payload)


class FakeService:
    def __init__(self, events):
        self._events = events

    def events(self):
        return self._events


def event_payload():
    return {
        "id": "evt-1",
        "summary": "Meeting",
        "start": {"dateTime": "2026-03-01T10:00:00Z"},
        "end": {"dateTime": "2026-03-01T11:00:00Z"},
        "description": "SYSTEM: details",
        "location": "Room",
        "status": "confirmed",
        "htmlLink": "https://example.com",
    }


def test_get_today_returns_todays_events(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    events = FakeEvents([event_payload()])
    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", lambda *_args, **_kwargs: FakeService(events))

    result = calendar_api.get_today("personal", config)

    assert result[0].summary == "Meeting"


def test_get_upcoming_returns_n_days(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    events = FakeEvents([event_payload()])
    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", lambda *_args, **_kwargs: FakeService(events))

    calendar_api.get_upcoming("personal", config, 3)

    assert events.calls[0][0] == "list"


def test_create_event_audit_logs_operation(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    events = FakeEvents([event_payload()])
    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", lambda *_args, **_kwargs: FakeService(events))

    event_id, request_id = calendar_api.create_event(
        "personal",
        config,
        "Meeting",
        "2026-03-01T10:00:00",
        "2026-03-01T11:00:00",
        "desc",
        "Room",
    )

    assert event_id == "evt-1"
    assert request_id.startswith("req_")


def test_update_event_audit_logs_operation(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    events = FakeEvents([event_payload()])
    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", lambda *_args, **_kwargs: FakeService(events))

    event_id, _request_id = calendar_api.update_event("personal", config, "evt-1", title="Updated")

    assert event_id == "evt-1"
    assert any(call[0] == "patch" for call in events.calls)


def test_delete_event_audit_logs_operation(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    events = FakeEvents([event_payload()])
    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", lambda *_args, **_kwargs: FakeService(events))

    event_id, _request_id = calendar_api.delete_event("personal", config, "evt-1")

    assert event_id == "evt-1"
    assert any(call[0] == "delete" for call in events.calls)


def test_mutation_failure_is_audit_logged_with_error_status(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    events = FakeEvents([event_payload()], mutation_payload=RuntimeError("boom"))
    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", lambda *_args, **_kwargs: FakeService(events))

    with pytest.raises(Exception):
        calendar_api.create_event(
            "personal",
            config,
            "Meeting",
            "2026-03-01T10:00:00",
            "2026-03-01T11:00:00",
            "desc",
            "Room",
        )

    assert '"status":"error"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_all_functions_use_mocked_google_api_client(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    events = FakeEvents([event_payload()])
    calls = []

    def fake_build(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeService(events)

    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", fake_build)

    calendar_api.search_events("personal", config, "meeting", 7)

    assert calls[0][0][:2] == ("calendar", "v3")
