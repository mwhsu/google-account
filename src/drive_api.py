from pathlib import Path

import click

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:  # pragma: no cover
    build = None
    MediaFileUpload = None

from src.audit import log_mutation
from src.auth import get_credentials
from src.config import AppConfig
from src.models import DriveFile, DriveFolder, DrivePermission
from src.pagination import paginate

DRIVE_FILE_FIELDS = "id,name,mimeType,modifiedTime,size,parents,webViewLink,trashed"

WORKSPACE_EXPORT_MIMES = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.drawing": ("application/pdf", ".pdf"),
}


def _drive_service(account: str, config: AppConfig):
    if build is None:
        raise click.ClickException("google-api-python-client is not installed")
    return build("drive", "v3", credentials=get_credentials(account, config))


def _escape_drive_query_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _file_to_model(data: dict) -> DriveFile:
    return DriveFile(
        id=data["id"],
        name=data.get("name", ""),
        mime_type=data.get("mimeType", ""),
        modified_time=data.get("modifiedTime", ""),
        size=data.get("size", ""),
        parents=data.get("parents", []),
        web_view_link=data.get("webViewLink", ""),
        trashed=data.get("trashed", False),
    )


def list_files(
    account: str, config: AppConfig, limit: int, folder: str | None = None
) -> list[DriveFile]:
    service = _drive_service(account, config)
    q = "trashed=false"
    if folder:
        q += f" and '{_escape_drive_query_literal(folder)}' in parents"

    def fetch_page(token):
        response = (
            service.files()
            .list(
                q=q,
                pageSize=min(limit, 100),
                pageToken=token,
                orderBy="modifiedTime desc",
                fields=f"files({DRIVE_FILE_FIELDS}),nextPageToken",
            )
            .execute()
        )
        items = [_file_to_model(f) for f in response.get("files", [])]
        return items, response.get("nextPageToken")

    items, _ = paginate(fetch_page, limit)
    return items


def search_files(
    account: str, config: AppConfig, query: str, limit: int
) -> list[DriveFile]:
    service = _drive_service(account, config)
    q = f"trashed=false and name contains '{_escape_drive_query_literal(query)}'"

    def fetch_page(token):
        response = (
            service.files()
            .list(
                q=q,
                pageSize=min(limit, 100),
                pageToken=token,
                orderBy="modifiedTime desc",
                fields=f"files({DRIVE_FILE_FIELDS}),nextPageToken",
            )
            .execute()
        )
        items = [_file_to_model(f) for f in response.get("files", [])]
        return items, response.get("nextPageToken")

    items, _ = paginate(fetch_page, limit)
    return items


def get_file(account: str, config: AppConfig, file_id: str) -> DriveFile:
    service = _drive_service(account, config)
    data = service.files().get(fileId=file_id, fields=DRIVE_FILE_FIELDS).execute()
    return _file_to_model(data)


def download_file(
    account: str, config: AppConfig, file_id: str
) -> tuple[bytes, str]:
    """Download file content. Returns (content_bytes, suggested_filename)."""
    service = _drive_service(account, config)
    metadata = (
        service.files().get(fileId=file_id, fields="name,mimeType,size").execute()
    )
    mime_type = metadata.get("mimeType", "")
    name = metadata.get("name", file_id)
    max_bytes = config.sanitization.max_download_bytes

    if mime_type in WORKSPACE_EXPORT_MIMES:
        export_mime, ext = WORKSPACE_EXPORT_MIMES[mime_type]
        content = (
            service.files()
            .export(fileId=file_id, mimeType=export_mime)
            .execute()
        )
        suggested_name = name + ext if not name.endswith(ext) else name
    else:
        file_size = int(metadata.get("size", "0") or "0")
        if file_size > max_bytes:
            raise click.ClickException(
                f"File too large: {file_size} bytes (limit: {max_bytes} bytes)"
            )
        content = service.files().get_media(fileId=file_id).execute()
        suggested_name = name

    if isinstance(content, str):
        content = content.encode("utf-8")

    if len(content) > max_bytes:
        raise click.ClickException(
            f"Download exceeded size limit ({max_bytes} bytes)"
        )

    return content, suggested_name


def upload_file(
    account: str,
    config: AppConfig,
    local_path: str,
    folder: str | None = None,
    name: str | None = None,
) -> tuple[str, str]:
    service = _drive_service(account, config)
    file_name = name or Path(local_path).name
    file_metadata: dict = {"name": file_name}
    if folder:
        file_metadata["parents"] = [folder]
    try:
        media = MediaFileUpload(local_path) if MediaFileUpload else None
        result = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id")
            .execute()
        )
    except Exception as exc:
        request_id = log_mutation(
            "drive.upload",
            account,
            "file",
            "unknown",
            "error",
            f"Upload {file_name}",
            config,
            error=str(exc),
            params={"name": file_name},
        )
        raise click.ClickException(f"Failed to upload | audit: {request_id}") from exc
    file_id = result["id"]
    request_id = log_mutation(
        "drive.upload",
        account,
        "file",
        file_id,
        "success",
        f"Upload {file_name}",
        config,
        params={"name": file_name},
    )
    return file_id, request_id


def create_folder(
    account: str,
    config: AppConfig,
    name: str,
    parent: str | None = None,
) -> tuple[str, str]:
    service = _drive_service(account, config)
    file_metadata: dict = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent:
        file_metadata["parents"] = [parent]
    try:
        result = service.files().create(body=file_metadata, fields="id").execute()
    except Exception as exc:
        request_id = log_mutation(
            "drive.create_folder",
            account,
            "folder",
            "unknown",
            "error",
            f"Create folder {name}",
            config,
            error=str(exc),
            params={"name": name},
        )
        raise click.ClickException(
            f"Failed to create folder | audit: {request_id}"
        ) from exc
    folder_id = result["id"]
    request_id = log_mutation(
        "drive.create_folder",
        account,
        "folder",
        folder_id,
        "success",
        f"Create folder {name}",
        config,
        params={"name": name},
    )
    return folder_id, request_id


def move_file(
    account: str, config: AppConfig, file_id: str, destination_folder: str
) -> tuple[str, str]:
    service = _drive_service(account, config)
    try:
        current = service.files().get(fileId=file_id, fields="parents").execute()
        previous_parents = ",".join(current.get("parents", []))
        service.files().update(
            fileId=file_id,
            addParents=destination_folder,
            removeParents=previous_parents,
            fields="id",
        ).execute()
    except Exception as exc:
        request_id = log_mutation(
            "drive.move",
            account,
            "file",
            file_id,
            "error",
            f"Move {file_id} to {destination_folder}",
            config,
            error=str(exc),
            params={"file_id": file_id, "destination": destination_folder},
        )
        raise click.ClickException(
            f"Failed to move file | audit: {request_id}"
        ) from exc
    request_id = log_mutation(
        "drive.move",
        account,
        "file",
        file_id,
        "success",
        f"Move {file_id} to {destination_folder}",
        config,
        params={"file_id": file_id, "destination": destination_folder},
    )
    return file_id, request_id


def rename_file(
    account: str, config: AppConfig, file_id: str, new_name: str
) -> tuple[str, str]:
    service = _drive_service(account, config)
    try:
        service.files().update(
            fileId=file_id, body={"name": new_name}, fields="id"
        ).execute()
    except Exception as exc:
        request_id = log_mutation(
            "drive.rename",
            account,
            "file",
            file_id,
            "error",
            f"Rename {file_id} to {new_name}",
            config,
            error=str(exc),
            params={"file_id": file_id, "new_name": new_name},
        )
        raise click.ClickException(
            f"Failed to rename file | audit: {request_id}"
        ) from exc
    request_id = log_mutation(
        "drive.rename",
        account,
        "file",
        file_id,
        "success",
        f"Rename {file_id} to {new_name}",
        config,
        params={"file_id": file_id, "new_name": new_name},
    )
    return file_id, request_id


def trash_file(
    account: str, config: AppConfig, file_id: str
) -> tuple[str, str]:
    service = _drive_service(account, config)
    try:
        service.files().update(
            fileId=file_id, body={"trashed": True}, fields="id"
        ).execute()
    except Exception as exc:
        request_id = log_mutation(
            "drive.trash",
            account,
            "file",
            file_id,
            "error",
            f"Trash {file_id}",
            config,
            error=str(exc),
            params={"file_id": file_id},
        )
        raise click.ClickException(
            f"Failed to trash file | audit: {request_id}"
        ) from exc
    request_id = log_mutation(
        "drive.trash",
        account,
        "file",
        file_id,
        "success",
        f"Trash {file_id}",
        config,
        params={"file_id": file_id},
    )
    return file_id, request_id


def delete_file(
    account: str, config: AppConfig, file_id: str
) -> tuple[str, str]:
    service = _drive_service(account, config)
    try:
        service.files().delete(fileId=file_id).execute()
    except Exception as exc:
        request_id = log_mutation(
            "drive.delete",
            account,
            "file",
            file_id,
            "error",
            f"Delete {file_id}",
            config,
            error=str(exc),
            params={"file_id": file_id},
        )
        raise click.ClickException(
            f"Failed to delete file | audit: {request_id}"
        ) from exc
    request_id = log_mutation(
        "drive.delete",
        account,
        "file",
        file_id,
        "success",
        f"Delete {file_id}",
        config,
        params={"file_id": file_id},
    )
    return file_id, request_id


def share_file(
    account: str,
    config: AppConfig,
    file_id: str,
    email: str,
    role: str,
) -> tuple[str, str]:
    service = _drive_service(account, config)
    permission = {"type": "user", "role": role, "emailAddress": email}
    try:
        result = (
            service.permissions()
            .create(
                fileId=file_id, body=permission, sendNotificationEmail=False
            )
            .execute()
        )
    except Exception as exc:
        request_id = log_mutation(
            "drive.share",
            account,
            "permission",
            file_id,
            "error",
            f"Share {file_id} with {email} ({role})",
            config,
            error=str(exc),
            params={"file_id": file_id, "email": email, "role": role},
        )
        raise click.ClickException(
            f"Failed to share file | audit: {request_id}"
        ) from exc
    perm_id = result.get("id", "")
    request_id = log_mutation(
        "drive.share",
        account,
        "permission",
        perm_id,
        "success",
        f"Share {file_id} with {email} ({role})",
        config,
        params={"file_id": file_id, "email": email, "role": role},
    )
    return perm_id, request_id


def list_permissions(
    account: str, config: AppConfig, file_id: str
) -> list[DrivePermission]:
    service = _drive_service(account, config)
    response = (
        service.permissions()
        .list(
            fileId=file_id,
            fields="permissions(id,role,type,emailAddress,displayName)",
        )
        .execute()
    )
    return [
        DrivePermission(
            id=p["id"],
            role=p.get("role", ""),
            type=p.get("type", ""),
            email_address=p.get("emailAddress", ""),
            display_name=p.get("displayName", ""),
        )
        for p in response.get("permissions", [])
    ]
