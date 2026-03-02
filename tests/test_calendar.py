import pytest

from src import calendar_api
from src.config import AppConfig


def make_config(tmp_path):
    return AppConfig.model_validate(
        {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "accounts": {
                "personal": {"description": "Personal", "calendar_id": "personal@example.com"},
                "family": {"description": "Family", "calendar_id": "family@example.com"},
            },
            "calendars": {"family": "family-calendar-id@group.calendar.google.com"},
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
    def __init__(self, events, freebusy=None):
        self._events = events
        self._freebusy = freebusy

    def events(self):
        return self._events

    def freebusy(self):
        return self._freebusy


class FakeFreeBusy:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(("query", kwargs))
        return ExecuteWrapper(self.payload)


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
    assert events.calls[0][1]["calendarId"] == "primary"


def test_get_today_uses_named_calendar_alias(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    events = FakeEvents([event_payload()])
    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", lambda *_args, **_kwargs: FakeService(events))

    calendar_api.get_today("personal", config, calendar="family")

    assert events.calls[0][1]["calendarId"] == "family-calendar-id@group.calendar.google.com"


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
        calendar="family",
    )

    assert event_id == "evt-1"
    assert request_id.startswith("req_")
    assert events.calls[0][1]["calendarId"] == "family-calendar-id@group.calendar.google.com"
    assert "calendar.create" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_update_event_audit_logs_operation(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    events = FakeEvents([event_payload()])
    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", lambda *_args, **_kwargs: FakeService(events))

    event_id, _request_id = calendar_api.update_event("personal", config, "evt-1", calendar="family", title="Updated")

    assert event_id == "evt-1"
    assert any(call[0] == "patch" for call in events.calls)
    assert events.calls[0][1]["calendarId"] == "family-calendar-id@group.calendar.google.com"
    assert "calendar.update" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_delete_event_audit_logs_operation(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    events = FakeEvents([event_payload()])
    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", lambda *_args, **_kwargs: FakeService(events))

    event_id, _request_id = calendar_api.delete_event("personal", config, "evt-1", calendar="family")

    assert event_id == "evt-1"
    assert any(call[0] == "delete" for call in events.calls)
    assert events.calls[0][1]["calendarId"] == "family-calendar-id@group.calendar.google.com"
    assert "calendar.delete" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


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


class PaginatedFakeEvents:
    """FakeEvents that returns different pages on successive list() calls."""

    def __init__(self, pages):
        self.pages = pages
        self.call_index = 0
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        page = self.pages[self.call_index]
        self.call_index += 1
        return ExecuteWrapper(page)


def test_get_upcoming_paginates_across_pages(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = [
        {"items": [event_payload()], "nextPageToken": "tok2"},
        {"items": [{**event_payload(), "id": "evt-2", "summary": "Lunch"}]},
    ]
    events = PaginatedFakeEvents(pages)
    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", lambda *_args, **_kwargs: FakeService(events))

    result = calendar_api.get_upcoming("personal", config, 7)

    assert len(result) == 2
    assert result[0].summary == "Meeting"
    assert result[1].summary == "Lunch"
    assert events.calls[1][1]["pageToken"] == "tok2"


def test_search_events_paginates_across_pages(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    evt1 = event_payload()
    evt2 = {**event_payload(), "id": "evt-2", "summary": "Standup"}
    pages = [
        {"items": [evt1], "nextPageToken": "tok2"},
        {"items": [evt2]},
    ]
    events = PaginatedFakeEvents(pages)
    monkeypatch.setattr(calendar_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calendar_api, "build", lambda *_args, **_kwargs: FakeService(events))

    result = calendar_api.search_events("personal", config, "meeting", 7)

    assert len(result) == 2
    assert result[0].summary == "Meeting"
    assert result[1].summary == "Standup"
    assert events.calls[1][1]["pageToken"] == "tok2"


def test_free_busy_and_overlap_removed():
    """Verify free-busy and overlap functions are no longer available."""
    assert not hasattr(calendar_api, "get_free_busy")
    assert not hasattr(calendar_api, "get_overlap")
