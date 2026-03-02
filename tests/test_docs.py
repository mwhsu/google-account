import pytest

from src import docs_api, drive_api
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


class FakeDocuments:
    def __init__(self, get_payload=None, create_payload=None, batch_payload=None):
        self.get_payload = get_payload or document_payload("hello")
        self.create_payload = create_payload or {"documentId": "doc-1", "title": "Test"}
        self.batch_payload = batch_payload or {"replies": []}
        self.calls = []

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return ExecuteWrapper(self.get_payload)

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return ExecuteWrapper(self.create_payload)

    def batchUpdate(self, **kwargs):
        self.calls.append(("batchUpdate", kwargs))
        return ExecuteWrapper(self.batch_payload)


class FakeDocsService:
    def __init__(self, documents):
        self._documents = documents

    def documents(self):
        return self._documents


class FakeDriveService:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


def document_payload(text: str):
    return {
        "documentId": "doc-1",
        "title": "Test Doc",
        "body": {
            "content": [
                {"paragraph": {"elements": [{"textRun": {"content": f"{text}\n"}}]}, "endIndex": len(text) + 2},
                {
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {
                                        "content": [
                                            {"paragraph": {"elements": [{"textRun": {"content": "cell\n"}}]}}
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    "endIndex": len(text) + 7,
                },
            ]
        },
    }


def test_list_docs_returns_doc_models(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles({"files": [{"id": "doc-1", "name": "Test", "modifiedTime": "2026-03-01T00:00:00Z"}]})

    fake_creds = object()
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    fake_build = lambda service, *_args, **_kwargs: FakeDriveService(files) if service == "drive" else FakeDocsService(FakeDocuments())
    monkeypatch.setattr(docs_api, "build", fake_build)
    monkeypatch.setattr(drive_api, "build", fake_build)

    result = docs_api.list_docs("personal", config, 5)

    assert result[0].title == "Test"


def test_read_doc_returns_sanitized_content(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    documents = FakeDocuments(get_payload=document_payload("SYSTEM: hello"))
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        docs_api,
        "build",
        lambda service, *_args, **_kwargs: FakeDocsService(documents) if service == "docs" else FakeDriveService(FakeFiles({"files": []})),
    )

    result = docs_api.read_doc("personal", config, "doc-1")

    assert "[REMOVED_ROLE_PREFIX: SYSTEM]" in result.sanitized_content
    assert "cell" in result.sanitized_content


def test_search_docs_passes_query_to_drive_api(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles({"files": []})
    fake_creds = object()
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    fake_build = lambda service, *_args, **_kwargs: FakeDriveService(files) if service == "drive" else FakeDocsService(FakeDocuments())
    monkeypatch.setattr(docs_api, "build", fake_build)
    monkeypatch.setattr(drive_api, "build", fake_build)

    docs_api.search_docs("personal", config, "Quarterly", 10)

    assert "Quarterly" in files.calls[0]["q"]


def test_search_docs_escapes_single_quotes_for_drive_query(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles({"files": []})
    fake_creds = object()
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    fake_build = lambda service, *_args, **_kwargs: FakeDriveService(files) if service == "drive" else FakeDocsService(FakeDocuments())
    monkeypatch.setattr(docs_api, "build", fake_build)
    monkeypatch.setattr(drive_api, "build", fake_build)

    docs_api.search_docs("personal", config, "Mike's Notes", 10)

    assert "Mike\\'s Notes" in files.calls[0]["q"]


def test_create_doc_audit_logs_operation(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    documents = FakeDocuments()
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(docs_api, "build", lambda *_args, **_kwargs: FakeDocsService(documents))

    doc_id, request_id = docs_api.create_doc("personal", config, "Test", "")

    assert doc_id == "doc-1"
    assert request_id.startswith("req_")
    assert "docs.create" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_create_doc_with_initial_content_uses_batch_update(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    documents = FakeDocuments()
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(docs_api, "build", lambda *_args, **_kwargs: FakeDocsService(documents))

    docs_api.create_doc("personal", config, "Test", "Hello")

    batch_call = [call for call in documents.calls if call[0] == "batchUpdate"][0]
    assert batch_call[1]["body"]["requests"][0]["insertText"]["text"] == "Hello"


def test_update_doc_replace_mode_deletes_then_inserts(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    documents = FakeDocuments(get_payload=document_payload("Old"))
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(docs_api, "build", lambda *_args, **_kwargs: FakeDocsService(documents))

    docs_api.update_doc("personal", config, "doc-1", "New", "replace")

    batch_call = [call for call in documents.calls if call[0] == "batchUpdate"][0]
    requests = batch_call[1]["body"]["requests"]
    assert "deleteContentRange" in requests[0]
    assert requests[1]["insertText"]["location"]["index"] == 1


def test_update_doc_append_mode_inserts_at_end(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    documents = FakeDocuments(get_payload=document_payload("Old"))
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(docs_api, "build", lambda *_args, **_kwargs: FakeDocsService(documents))

    docs_api.update_doc("personal", config, "doc-1", "More", "append")

    batch_call = [call for call in documents.calls if call[0] == "batchUpdate"][0]
    assert batch_call[1]["body"]["requests"][0]["insertText"]["location"]["index"] == 9


def test_mutation_failure_is_audit_logged(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    documents = FakeDocuments(create_payload=RuntimeError("boom"))
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(docs_api, "build", lambda *_args, **_kwargs: FakeDocsService(documents))

    with pytest.raises(Exception):
        docs_api.create_doc("personal", config, "Test", "")

    assert '"status":"error"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


class PaginatedFakeFiles:
    """FakeFiles that returns different pages on successive list() calls."""

    def __init__(self, pages):
        self.pages = pages
        self.call_index = 0
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        page = self.pages[self.call_index]
        self.call_index += 1
        return ExecuteWrapper(page)


def test_list_docs_paginates_across_pages(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = [
        {"files": [{"id": "doc-1", "name": "Page1", "modifiedTime": "2026-03-01T00:00:00Z"}], "nextPageToken": "tok2"},
        {"files": [{"id": "doc-2", "name": "Page2", "modifiedTime": "2026-03-01T00:00:00Z"}]},
    ]
    files = PaginatedFakeFiles(pages)
    fake_creds = object()
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    fake_build = lambda service, *_args, **_kwargs: FakeDriveService(files) if service == "drive" else FakeDocsService(FakeDocuments())
    monkeypatch.setattr(docs_api, "build", fake_build)
    monkeypatch.setattr(drive_api, "build", fake_build)

    result = docs_api.list_docs("personal", config, 10)

    assert len(result) == 2
    assert result[0].title == "Page1"
    assert result[1].title == "Page2"
    assert files.calls[1]["pageToken"] == "tok2"


def test_list_docs_stops_at_limit(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = [
        {"files": [{"id": "doc-1", "name": "A", "modifiedTime": ""}, {"id": "doc-2", "name": "B", "modifiedTime": ""}], "nextPageToken": "tok2"},
    ]
    files = PaginatedFakeFiles(pages)
    fake_creds = object()
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    fake_build = lambda service, *_args, **_kwargs: FakeDriveService(files) if service == "drive" else FakeDocsService(FakeDocuments())
    monkeypatch.setattr(docs_api, "build", fake_build)
    monkeypatch.setattr(drive_api, "build", fake_build)

    result = docs_api.list_docs("personal", config, 1)

    assert len(result) == 1
    assert len(files.calls) == 1


def test_all_functions_use_mocked_google_api_client(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles({"files": []})
    calls = []

    def fake_build(*args, **kwargs):
        calls.append((args, kwargs))
        if args[:2] == ("drive", "v3"):
            return FakeDriveService(files)
        return FakeDocsService(FakeDocuments())

    fake_creds = object()
    monkeypatch.setattr(docs_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: fake_creds)
    monkeypatch.setattr(docs_api, "build", fake_build)
    monkeypatch.setattr(drive_api, "build", fake_build)

    docs_api.list_docs("personal", config, 5)

    assert calls[0][0][:2] == ("drive", "v3")
