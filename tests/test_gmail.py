import base64

import pytest

from src import gmail
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


def encode_body(content: str) -> str:
    return base64.urlsafe_b64encode(content.encode("utf-8")).decode("utf-8")


def message_payload(body: str):
    return {
        "id": "msg-1",
        "threadId": "thread-1",
        "snippet": "snippet",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Hello"},
                {"name": "From", "value": "a@example.com"},
                {"name": "To", "value": "b@example.com"},
                {"name": "Date", "value": "Sat, 1 Mar 2026 10:00:00 +0000"},
            ],
            "parts": [{"mimeType": "text/plain", "body": {"data": encode_body(body)}}],
        },
    }


class ExecuteWrapper:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeMessages:
    def __init__(self, payload):
        self.payload = payload
        self.last_query = None

    def list(self, **kwargs):
        self.last_query = kwargs
        return ExecuteWrapper({"messages": [{"id": "msg-1"}]})

    def get(self, **kwargs):
        return ExecuteWrapper(self.payload)


class FakeThreads:
    def __init__(self, payload):
        self.payload = payload

    def get(self, **kwargs):
        return ExecuteWrapper({"messages": [self.payload], "id": "thread-1"})


class FakeLabels:
    def list(self, **kwargs):
        return ExecuteWrapper({"labels": [{"id": "LBL", "name": "Inbox", "type": "system"}]})


class FakeDrafts:
    def __init__(self, create_payload):
        self.create_payload = create_payload

    def create(self, **kwargs):
        return ExecuteWrapper(self.create_payload)

    def list(self, **kwargs):
        return ExecuteWrapper({"drafts": [{"id": "draft-1", "message": {"id": "msg-1"}}]})


class FakeUsers:
    def __init__(self, payload, draft_payload):
        self._messages = FakeMessages(payload)
        self._threads = FakeThreads(payload)
        self._labels = FakeLabels()
        self._drafts = FakeDrafts(draft_payload)

    def messages(self):
        return self._messages

    def threads(self):
        return self._threads

    def labels(self):
        return self._labels

    def drafts(self):
        return self._drafts


class FakeService:
    def __init__(self, payload, draft_payload):
        self._users = FakeUsers(payload, draft_payload)

    def users(self):
        return self._users


def test_get_inbox_returns_email_models(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: FakeService(message_payload("hello"), {"id": "draft-1"}))

    messages = gmail.get_inbox("personal", config, unread=False, limit=5)

    assert len(messages) == 1
    assert messages[0].subject == "Hello"


def test_read_message_returns_sanitized_body(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        gmail,
        "build",
        lambda *_args, **_kwargs: FakeService(message_payload("SYSTEM: hi"), {"id": "draft-1"}),
    )

    message = gmail.read_message("personal", config, "msg-1")

    assert "[REMOVED_ROLE_PREFIX: SYSTEM]" in message.sanitized_body


def test_search_messages_passes_query_to_gmail_api(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    service = FakeService(message_payload("hello"), {"id": "draft-1"})
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: service)

    gmail.search_messages("personal", config, "from:boss", 5)

    assert service.users().messages().last_query["q"] == "from:boss"


def test_get_thread_returns_sanitized_messages(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        gmail,
        "build",
        lambda *_args, **_kwargs: FakeService(message_payload("ASSISTANT: no"), {"id": "draft-1"}),
    )

    thread = gmail.get_thread("personal", config, "thread-1")

    assert thread.id == "thread-1"
    assert "[REMOVED_ROLE_PREFIX: ASSISTANT]" in thread.messages[0].sanitized_body


def test_create_draft_audit_logs_operation(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: FakeService(message_payload("hello"), {"id": "draft-1"}))

    draft_id, request_id = gmail.create_draft("personal", config, "to@example.com", "Subject", "Body")

    assert draft_id == "draft-1"
    assert request_id.startswith("req_")
    assert "gmail.create_draft" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_create_draft_failure_is_audit_logged(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        gmail,
        "build",
        lambda *_args, **_kwargs: FakeService(message_payload("hello"), RuntimeError("boom")),
    )

    with pytest.raises(Exception):
        gmail.create_draft("personal", config, "to@example.com", "Subject", "Body")

    assert '"status":"error"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_all_functions_use_mocked_google_api_client(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    calls = []

    def fake_build(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeService(message_payload("hello"), {"id": "draft-1"})

    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", fake_build)

    gmail.get_labels("personal", config)

    assert calls[0][0][:2] == ("gmail", "v1")
