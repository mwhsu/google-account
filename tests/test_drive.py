import pytest

from src import drive_api
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
    def __init__(self, list_payload=None, get_payload=None, create_payload=None,
                 update_payload=None, delete_payload=None, export_payload=None,
                 get_media_payload=None):
        self.list_payload = list_payload or {"files": []}
        self.get_payload = get_payload or {}
        self.create_payload = create_payload or {"id": "file-1"}
        self.update_payload = update_payload or {"id": "file-1"}
        self.delete_payload = delete_payload or {}
        self.export_payload = export_payload or b"exported content"
        self.get_media_payload = get_media_payload or b"file content"
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return ExecuteWrapper(self.list_payload)

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return ExecuteWrapper(self.get_payload)

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return ExecuteWrapper(self.create_payload)

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return ExecuteWrapper(self.update_payload)

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return ExecuteWrapper(self.delete_payload)

    def export(self, **kwargs):
        self.calls.append(("export", kwargs))
        return ExecuteWrapper(self.export_payload)

    def get_media(self, **kwargs):
        self.calls.append(("get_media", kwargs))
        return ExecuteWrapper(self.get_media_payload)


class FakePermissions:
    def __init__(self, list_payload=None, create_payload=None):
        self.list_payload = list_payload or {"permissions": []}
        self.create_payload = create_payload or {"id": "perm-1"}
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return ExecuteWrapper(self.list_payload)

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return ExecuteWrapper(self.create_payload)


class FakeDriveService:
    def __init__(self, files, permissions=None):
        self._files = files
        self._permissions = permissions or FakePermissions()

    def files(self):
        return self._files

    def permissions(self):
        return self._permissions


def file_payload(file_id="file-1", name="Report.pdf", mime_type="application/pdf"):
    return {
        "id": file_id,
        "name": name,
        "mimeType": mime_type,
        "modifiedTime": "2026-03-01T00:00:00Z",
        "size": "1024",
        "parents": ["root"],
        "webViewLink": "https://drive.google.com/file/d/file-1",
        "trashed": False,
    }


def test_list_files_returns_drive_file_models(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(list_payload={"files": [file_payload()]})
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    result = drive_api.list_files("personal", config, 10)

    assert result[0].name == "Report.pdf"
    assert result[0].id == "file-1"


def test_list_files_with_folder_filter(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(list_payload={"files": []})
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    drive_api.list_files("personal", config, 10, folder="folder-1")

    assert "'folder-1' in parents" in files.calls[0][1]["q"]


def test_search_files_passes_query(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(list_payload={"files": [file_payload()]})
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    result = drive_api.search_files("personal", config, "Report", 10)

    assert "Report" in files.calls[0][1]["q"]
    assert len(result) == 1


def test_search_files_escapes_single_quotes(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(list_payload={"files": []})
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    drive_api.search_files("personal", config, "Mike's Report", 10)

    assert "Mike\\'s Report" in files.calls[0][1]["q"]


def test_get_file_returns_model(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(get_payload=file_payload())
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    result = drive_api.get_file("personal", config, "file-1")

    assert result.id == "file-1"
    assert result.name == "Report.pdf"


def test_download_regular_file(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    metadata = {"name": "data.csv", "mimeType": "text/csv", "size": "100"}
    # get is called twice: once for metadata, once would be get_media
    call_count = {"n": 0}
    original_get_payload = metadata
    media_payload = b"col1,col2\na,b"

    files = FakeFiles(get_payload=metadata, get_media_payload=media_payload)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    content, name = drive_api.download_file("personal", config, "file-1")

    assert content == media_payload
    assert name == "data.csv"


def test_download_workspace_doc_exports_as_text(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    metadata = {"name": "My Doc", "mimeType": "application/vnd.google-apps.document", "size": "0"}
    exported = b"Hello world"
    files = FakeFiles(get_payload=metadata, export_payload=exported)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    content, name = drive_api.download_file("personal", config, "doc-1")

    assert content == exported
    assert name == "My Doc.txt"
    export_call = [c for c in files.calls if c[0] == "export"][0]
    assert export_call[1]["mimeType"] == "text/plain"


def test_download_rejects_oversized_file(tmp_path, monkeypatch):
    config = AppConfig.model_validate(
        {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "accounts": {"personal": {"description": "Personal"}},
            "sanitization": {"max_download_bytes": 50},
            "logging": {"audit_log_path": str(tmp_path / "audit.jsonl")},
        }
    )
    metadata = {"name": "big.zip", "mimeType": "application/zip", "size": "100"}
    files = FakeFiles(get_payload=metadata)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    with pytest.raises(Exception, match="File too large"):
        drive_api.download_file("personal", config, "file-1")


def test_upload_file_audit_logs(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(create_payload={"id": "uploaded-1"})
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))
    monkeypatch.setattr(drive_api, "MediaFileUpload", lambda path: f"media:{path}")

    local = tmp_path / "test.txt"
    local.write_text("hello", encoding="utf-8")

    file_id, request_id = drive_api.upload_file("personal", config, str(local))

    assert file_id == "uploaded-1"
    assert request_id.startswith("req_")
    assert "drive.upload" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_upload_file_with_folder_and_name(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(create_payload={"id": "uploaded-2"})
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))
    monkeypatch.setattr(drive_api, "MediaFileUpload", lambda path: f"media:{path}")

    local = tmp_path / "test.txt"
    local.write_text("hello", encoding="utf-8")

    drive_api.upload_file("personal", config, str(local), folder="folder-1", name="renamed.txt")

    create_call = [c for c in files.calls if c[0] == "create"][0]
    assert create_call[1]["body"]["name"] == "renamed.txt"
    assert create_call[1]["body"]["parents"] == ["folder-1"]


def test_create_folder_audit_logs(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(create_payload={"id": "folder-new"})
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    folder_id, request_id = drive_api.create_folder("personal", config, "New Folder")

    assert folder_id == "folder-new"
    assert request_id.startswith("req_")
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "drive.create_folder" in audit


def test_create_folder_with_parent(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(create_payload={"id": "folder-child"})
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    drive_api.create_folder("personal", config, "Child", parent="parent-1")

    create_call = [c for c in files.calls if c[0] == "create"][0]
    assert create_call[1]["body"]["parents"] == ["parent-1"]
    assert create_call[1]["body"]["mimeType"] == "application/vnd.google-apps.folder"


def test_move_file_audit_logs(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(
        get_payload={"parents": ["old-folder"]},
        update_payload={"id": "file-1"},
    )
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    file_id, request_id = drive_api.move_file("personal", config, "file-1", "new-folder")

    assert file_id == "file-1"
    update_call = [c for c in files.calls if c[0] == "update"][0]
    assert update_call[1]["addParents"] == "new-folder"
    assert update_call[1]["removeParents"] == "old-folder"
    assert "drive.move" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_rename_file_audit_logs(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(update_payload={"id": "file-1"})
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    file_id, request_id = drive_api.rename_file("personal", config, "file-1", "New Name.pdf")

    assert file_id == "file-1"
    update_call = [c for c in files.calls if c[0] == "update"][0]
    assert update_call[1]["body"]["name"] == "New Name.pdf"
    assert "drive.rename" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_trash_file_audit_logs(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(update_payload={"id": "file-1"})
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    file_id, request_id = drive_api.trash_file("personal", config, "file-1")

    assert file_id == "file-1"
    update_call = [c for c in files.calls if c[0] == "update"][0]
    assert update_call[1]["body"]["trashed"] is True
    assert "drive.trash" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_delete_file_audit_logs(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles()
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    file_id, request_id = drive_api.delete_file("personal", config, "file-1")

    assert file_id == "file-1"
    assert any(c[0] == "delete" for c in files.calls)
    assert "drive.delete" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_share_file_audit_logs(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    permissions = FakePermissions(create_payload={"id": "perm-1"})
    files = FakeFiles()
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files, permissions))

    perm_id, request_id = drive_api.share_file("personal", config, "file-1", "user@example.com", "reader")

    assert perm_id == "perm-1"
    create_call = [c for c in permissions.calls if c[0] == "create"][0]
    assert create_call[1]["body"]["emailAddress"] == "user@example.com"
    assert create_call[1]["body"]["role"] == "reader"
    assert "drive.share" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_list_permissions_returns_models(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    permissions = FakePermissions(
        list_payload={
            "permissions": [
                {"id": "perm-1", "role": "owner", "type": "user", "emailAddress": "me@example.com", "displayName": "Me"}
            ]
        }
    )
    files = FakeFiles()
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files, permissions))

    result = drive_api.list_permissions("personal", config, "file-1")

    assert result[0].id == "perm-1"
    assert result[0].role == "owner"
    assert result[0].email_address == "me@example.com"


def test_mutation_failure_is_audit_logged(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = FakeFiles(create_payload=RuntimeError("boom"))
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    with pytest.raises(Exception):
        drive_api.create_folder("personal", config, "Test")

    assert '"status":"error"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


class PaginatedFakeFiles:
    """FakeFiles that returns different pages on successive list() calls."""

    def __init__(self, pages):
        self.pages = pages  # list of response dicts
        self.call_index = 0
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        page = self.pages[self.call_index]
        self.call_index += 1
        return ExecuteWrapper(page)


def test_list_files_paginates_across_pages(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = [
        {"files": [file_payload("file-1", "Page1.pdf")], "nextPageToken": "tok2"},
        {"files": [file_payload("file-2", "Page2.pdf")]},
    ]
    files = PaginatedFakeFiles(pages)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    result = drive_api.list_files("personal", config, 10)

    assert len(result) == 2
    assert result[0].name == "Page1.pdf"
    assert result[1].name == "Page2.pdf"
    # Second call should pass the page token
    assert files.calls[1][1]["pageToken"] == "tok2"


def test_list_files_stops_at_limit(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = [
        {"files": [file_payload("file-1"), file_payload("file-2")], "nextPageToken": "tok2"},
    ]
    files = PaginatedFakeFiles(pages)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    result = drive_api.list_files("personal", config, 1)

    assert len(result) == 1
    # Should not fetch second page since limit already reached
    assert len(files.calls) == 1


def test_search_files_paginates_across_pages(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = [
        {"files": [file_payload("file-1", "A.pdf")], "nextPageToken": "tok2"},
        {"files": [file_payload("file-2", "B.pdf")]},
    ]
    files = PaginatedFakeFiles(pages)
    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", lambda *_args, **_kwargs: FakeDriveService(files))

    result = drive_api.search_files("personal", config, "file", 10)

    assert len(result) == 2
    assert files.calls[1][1]["pageToken"] == "tok2"


def test_all_functions_use_mocked_google_api_client(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    calls = []

    def fake_build(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeDriveService(FakeFiles(list_payload={"files": [file_payload()]}))

    monkeypatch.setattr(drive_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(drive_api, "build", fake_build)

    drive_api.list_files("personal", config, 10)

    assert calls[0][0][:2] == ("drive", "v3")
