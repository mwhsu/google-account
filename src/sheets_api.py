import click

try:
    from googleapiclient.discovery import build
except ImportError:  # pragma: no cover - exercised only in dependency-light test envs
    build = None

from src.audit import log_mutation
from src.auth import get_credentials
from src.config import AppConfig
from src.models import SheetInfo, SheetRange
from src.sanitizer import sanitize


SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


def _sheets_service(account: str, config: AppConfig):
    if build is None:
        raise click.ClickException("google-api-python-client is not installed")
    return build("sheets", "v4", credentials=get_credentials(account, config))


def _drive_service(account: str, config: AppConfig):
    if build is None:
        raise click.ClickException("google-api-python-client is not installed")
    return build("drive", "v3", credentials=get_credentials(account, config))


def _drive_sheet_query(extra_query: str | None = None) -> str:
    query = f"mimeType='{SHEET_MIME_TYPE}' and trashed=false"
    if extra_query:
        query = f"{query} and ({extra_query})"
    return query


def _file_to_sheet_info(file_data: dict) -> SheetInfo:
    return SheetInfo(
        id=file_data["id"],
        title=file_data.get("name", ""),
        modified_time=file_data.get("modifiedTime", ""),
    )


def _bounded_values(values: list[list[str]], max_cells: int) -> list[list[str]]:
    bounded = []
    seen_cells = 0
    for row in values:
        bounded_row = []
        for value in row:
            if seen_cells >= max_cells:
                break
            bounded_row.append(value)
            seen_cells += 1
        if bounded_row:
            bounded.append(bounded_row)
        if seen_cells >= max_cells:
            break
    return bounded


def _sanitize_values(values: list[list[object]], config: AppConfig) -> list[list[str]]:
    string_values = [[str(value) for value in row] for row in values]
    bounded = _bounded_values(string_values, config.sanitization.max_sheet_cells)
    return [
        [
            sanitize(
                value,
                "SHEET_RANGE",
                config.sanitization.max_doc_chars,
                strip_html=config.sanitization.strip_html,
                neutralize=config.sanitization.neutralize_injections,
            )
            for value in row
        ]
        for row in bounded
    ]


def format_sheet_table(sheet_range: SheetRange) -> str:
    rows = sheet_range.sanitized_values
    if not rows:
        return "(empty)"
    widths = [max(len(row[index]) for row in rows if index < len(row)) for index in range(max(len(row) for row in rows))]
    lines = []
    for row in rows:
        padded = [row[index].ljust(widths[index]) if index < len(row) else "".ljust(widths[index]) for index in range(len(widths))]
        lines.append(" | ".join(padded).rstrip())
    return "\n".join(lines)


def list_sheets(account: str, config: AppConfig, limit: int) -> list[SheetInfo]:
    service = _drive_service(account, config)
    response = (
        service.files()
        .list(
            q=_drive_sheet_query(),
            pageSize=limit,
            orderBy="modifiedTime desc",
            fields="files(id,name,modifiedTime)",
        )
        .execute()
    )
    return [_file_to_sheet_info(file_data) for file_data in response.get("files", [])]


def read_sheet(account: str, config: AppConfig, sheet_id: str, range_name: str = "Sheet1") -> SheetRange:
    service = _sheets_service(account, config)
    response = service.spreadsheets().values().get(spreadsheetId=sheet_id, range=range_name).execute()
    return SheetRange(
        spreadsheet_id=sheet_id,
        range=response.get("range", range_name),
        sanitized_values=_sanitize_values(response.get("values", []), config),
    )


def search_sheets(account: str, config: AppConfig, query: str, limit: int) -> list[SheetInfo]:
    service = _drive_service(account, config)
    response = (
        service.files()
        .list(
            q=_drive_sheet_query(f"name contains '{query}'"),
            pageSize=limit,
            orderBy="modifiedTime desc",
            fields="files(id,name,modifiedTime)",
        )
        .execute()
    )
    return [_file_to_sheet_info(file_data) for file_data in response.get("files", [])]


def create_sheet(account: str, config: AppConfig, title: str, rows: int, cols: int) -> tuple[str, str]:
    service = _sheets_service(account, config)
    body = {
        "properties": {"title": title},
        "sheets": [{"properties": {"gridProperties": {"rowCount": rows, "columnCount": cols}}}],
    }
    try:
        response = service.spreadsheets().create(body=body).execute()
    except Exception as exc:
        request_id = log_mutation(
            "sheets.create_sheet",
            account,
            "sheet",
            "unknown",
            "error",
            f"Create sheet {title}",
            config,
            error=str(exc),
        )
        raise click.ClickException(f"Failed to create sheet | audit: {request_id}") from exc
    sheet_id = response["spreadsheetId"]
    request_id = log_mutation(
        "sheets.create_sheet",
        account,
        "sheet",
        sheet_id,
        "success",
        f"Create sheet {title}",
        config,
    )
    return sheet_id, request_id


def update_sheet(
    account: str,
    config: AppConfig,
    sheet_id: str,
    range_name: str,
    values: list[list[object]],
) -> tuple[str, str]:
    service = _sheets_service(account, config)
    try:
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
    except Exception as exc:
        request_id = log_mutation(
            "sheets.update_sheet",
            account,
            "sheet",
            sheet_id,
            "error",
            f"Update sheet {sheet_id} ({range_name})",
            config,
            error=str(exc),
        )
        raise click.ClickException(f"Failed to update sheet | audit: {request_id}") from exc
    request_id = log_mutation(
        "sheets.update_sheet",
        account,
        "sheet",
        sheet_id,
        "success",
        f"Update sheet {sheet_id} ({range_name})",
        config,
    )
    return sheet_id, request_id
