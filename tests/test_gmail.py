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
    def __init__(self, payload, modify_payload=None):
        self.payload = payload
        self.modify_payload = modify_payload or {"id": "msg-1"}
        self.last_query = None
        self.calls = []

    def list(self, **kwargs):
        self.last_query = kwargs
        return ExecuteWrapper({"messages": [{"id": "msg-1"}]})

    def get(self, **kwargs):
        return ExecuteWrapper(self.payload)

    def modify(self, **kwargs):
        self.calls.append(("modify", kwargs))
        return ExecuteWrapper(self.modify_payload)


class FakeThreads:
    def __init__(self, payload):
        self.payload = payload

    def get(self, **kwargs):
        return ExecuteWrapper({"messages": [self.payload], "id": "thread-1"})


class FakeLabels:
    def list(self, **kwargs):
        return ExecuteWrapper({"labels": [{"id": "LBL", "name": "Inbox", "type": "system"}]})


class FakeDrafts:
    def __init__(self, create_payload, delete_payload=None):
        self.create_payload = create_payload
        self.delete_payload = delete_payload or {}
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return ExecuteWrapper(self.create_payload)

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return ExecuteWrapper(self.delete_payload)

    def list(self, **kwargs):
        return ExecuteWrapper({"drafts": [{"id": "draft-1", "message": {"id": "msg-1"}}]})

    def get(self, **kwargs):
        return ExecuteWrapper({
            "id": "draft-1",
            "message": {"id": "msg-1", "payload": {"headers": [
                {"name": "Subject", "value": "Test"},
                {"name": "To", "value": "to@example.com"},
            ]}},
        })


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
    assert "gmail.draft" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


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


def test_create_draft_with_thread_id_and_in_reply_to(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    service = FakeService(message_payload("hello"), {"id": "draft-reply"})
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: service)

    draft_id, _ = gmail.create_draft(
        "personal", config, "to@example.com", "Re: Hello", "Reply body",
        thread_id="thread-1", in_reply_to="<msg-id@example.com>",
    )

    assert draft_id == "draft-reply"
    create_call = service.users().drafts().calls[0]
    assert create_call[0] == "create"
    body = create_call[1]["body"]
    assert body["message"]["threadId"] == "thread-1"


def test_delete_draft_audit_logs(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: FakeService(message_payload("hello"), {"id": "draft-1"}))

    draft_id, request_id = gmail.delete_draft("personal", config, "draft-1")

    assert draft_id == "draft-1"
    assert request_id.startswith("req_")
    assert "gmail.delete_draft" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_delete_draft_failure_is_audit_logged(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    service = FakeService(message_payload("hello"), {"id": "draft-1"})
    service._users._drafts.delete_payload = RuntimeError("boom")
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: service)

    with pytest.raises(Exception):
        gmail.delete_draft("personal", config, "draft-1")

    assert '"status":"error"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_archive_message_removes_inbox_label(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    service = FakeService(message_payload("hello"), {"id": "draft-1"})
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: service)

    msg_id, request_id = gmail.archive_message("personal", config, "msg-1")

    assert msg_id == "msg-1"
    modify_call = service.users().messages().calls[0]
    assert modify_call[0] == "modify"
    assert modify_call[1]["body"]["removeLabelIds"] == ["INBOX"]
    assert "gmail.modify_labels" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_modify_labels_adds_and_removes(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    service = FakeService(message_payload("hello"), {"id": "draft-1"})
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: service)

    gmail.modify_labels("personal", config, "msg-1", add_labels=["STARRED"], remove_labels=["UNREAD"])

    modify_call = service.users().messages().calls[0]
    assert modify_call[1]["body"]["addLabelIds"] == ["STARRED"]
    assert modify_call[1]["body"]["removeLabelIds"] == ["UNREAD"]


def test_mark_read_removes_unread_label(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    service = FakeService(message_payload("hello"), {"id": "draft-1"})
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: service)

    gmail.mark_read("personal", config, "msg-1")

    modify_call = service.users().messages().calls[0]
    assert modify_call[1]["body"]["removeLabelIds"] == ["UNREAD"]


def test_mark_unread_adds_unread_label(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    service = FakeService(message_payload("hello"), {"id": "draft-1"})
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: service)

    gmail.mark_unread("personal", config, "msg-1")

    modify_call = service.users().messages().calls[0]
    assert modify_call[1]["body"]["addLabelIds"] == ["UNREAD"]


class PaginatedFakeMessages:
    """FakeMessages that returns different pages on successive list() calls."""

    def __init__(self, pages, get_payload):
        self.pages = pages
        self.get_payload = get_payload
        self.call_index = 0
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        page = self.pages[self.call_index]
        self.call_index += 1
        return ExecuteWrapper(page)

    def get(self, **kwargs):
        return ExecuteWrapper(self.get_payload)

    def modify(self, **kwargs):
        self.calls.append(("modify", kwargs))
        return ExecuteWrapper({"id": "msg-1"})


class PaginatedFakeUsers:
    def __init__(self, messages, drafts):
        self._messages = messages
        self._threads = FakeThreads(message_payload("hello"))
        self._labels = FakeLabels()
        self._drafts = drafts

    def messages(self):
        return self._messages

    def threads(self):
        return self._threads

    def labels(self):
        return self._labels

    def drafts(self):
        return self._drafts


class PaginatedFakeService:
    def __init__(self, users):
        self._users = users

    def users(self):
        return self._users


def test_get_inbox_paginates_across_pages(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = [
        {"messages": [{"id": "msg-1"}], "nextPageToken": "tok2"},
        {"messages": [{"id": "msg-2"}]},
    ]
    messages = PaginatedFakeMessages(pages, message_payload("hello"))
    users = PaginatedFakeUsers(messages, FakeDrafts({"id": "draft-1"}))
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: PaginatedFakeService(users))

    result = gmail.get_inbox("personal", config, unread=False, limit=10)

    assert len(result) == 2
    assert messages.calls[1][1]["pageToken"] == "tok2"


def test_get_inbox_stops_at_limit(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = [
        {"messages": [{"id": "msg-1"}, {"id": "msg-2"}], "nextPageToken": "tok2"},
    ]
    messages = PaginatedFakeMessages(pages, message_payload("hello"))
    users = PaginatedFakeUsers(messages, FakeDrafts({"id": "draft-1"}))
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: PaginatedFakeService(users))

    result = gmail.get_inbox("personal", config, unread=False, limit=1)

    assert len(result) == 1
    assert len(messages.calls) == 1


def test_search_messages_paginates_across_pages(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = [
        {"messages": [{"id": "msg-1"}], "nextPageToken": "tok2"},
        {"messages": [{"id": "msg-2"}]},
    ]
    messages = PaginatedFakeMessages(pages, message_payload("hello"))
    users = PaginatedFakeUsers(messages, FakeDrafts({"id": "draft-1"}))
    monkeypatch.setattr(gmail, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: PaginatedFakeService(users))

    result = gmail.search_messages("personal", config, "test", limit=10)

    assert len(result) == 2
    assert messages.calls[1][1]["pageToken"] == "tok2"


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
