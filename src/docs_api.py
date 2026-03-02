import click

try:
    from googleapiclient.discovery import build
except ImportError:  # pragma: no cover - exercised only in dependency-light test envs
    build = None

from src.audit import log_mutation
from src.auth import get_credentials
from src.config import AppConfig
from src.drive_api import _drive_service, _escape_drive_query_literal
from src.models import DocContent, DocInfo
from src.pagination import paginate
from src.sanitizer import sanitize


DOC_MIME_TYPE = "application/vnd.google-apps.document"


def _docs_service(account: str, config: AppConfig):
    if build is None:
        raise click.ClickException("google-api-python-client is not installed")
    return build("docs", "v1", credentials=get_credentials(account, config))


def _drive_doc_query(extra_query: str | None = None) -> str:
    query = f"mimeType='{DOC_MIME_TYPE}' and trashed=false"
    if extra_query:
        query = f"{query} and ({extra_query})"
    return query


def _file_to_doc_info(file_data: dict) -> DocInfo:
    return DocInfo(
        id=file_data["id"],
        title=file_data.get("name", ""),
        modified_time=file_data.get("modifiedTime", ""),
    )


def _extract_text_from_paragraph(paragraph: dict) -> str:
    parts = []
    for element in paragraph.get("elements", []):
        text_run = element.get("textRun")
        if text_run:
            parts.append(text_run.get("content", ""))
    return "".join(parts)


def _extract_text_from_table(table: dict) -> str:
    parts = []
    for row in table.get("tableRows", []):
        for cell in row.get("tableCells", []):
            for content in cell.get("content", []):
                parts.append(_extract_text(content))
    return "".join(parts)


def _extract_text(structural_element: dict) -> str:
    if "paragraph" in structural_element:
        return _extract_text_from_paragraph(structural_element["paragraph"])
    if "table" in structural_element:
        return _extract_text_from_table(structural_element["table"])
    if "tableOfContents" in structural_element:
        return "".join(_extract_text(item) for item in structural_element["tableOfContents"].get("content", []))
    return ""


def _document_to_model(document: dict, config: AppConfig) -> DocContent:
    raw_content = "".join(_extract_text(item) for item in document.get("body", {}).get("content", []))
    return DocContent(
        id=document["documentId"],
        title=document.get("title", ""),
        sanitized_content=sanitize(
            raw_content,
            "DOC_CONTENT",
            config.sanitization.max_doc_chars,
            strip_html=config.sanitization.strip_html,
            neutralize=config.sanitization.neutralize_injections,
        ),
    )


def list_docs(account: str, config: AppConfig, limit: int) -> list[DocInfo]:
    service = _drive_service(account, config)

    def fetch_page(token):
        response = (
            service.files()
            .list(
                q=_drive_doc_query(),
                pageSize=min(limit, 100),
                pageToken=token,
                orderBy="modifiedTime desc",
                fields="files(id,name,modifiedTime),nextPageToken",
            )
            .execute()
        )
        items = [_file_to_doc_info(f) for f in response.get("files", [])]
        return items, response.get("nextPageToken")

    items, _ = paginate(fetch_page, limit)
    return items


def read_doc(account: str, config: AppConfig, doc_id: str) -> DocContent:
    service = _docs_service(account, config)
    document = service.documents().get(documentId=doc_id).execute()
    return _document_to_model(document, config)


def search_docs(account: str, config: AppConfig, query: str, limit: int) -> list[DocInfo]:
    service = _drive_service(account, config)
    q = _drive_doc_query(f"name contains '{_escape_drive_query_literal(query)}'")

    def fetch_page(token):
        response = (
            service.files()
            .list(
                q=q,
                pageSize=min(limit, 100),
                pageToken=token,
                orderBy="modifiedTime desc",
                fields="files(id,name,modifiedTime),nextPageToken",
            )
            .execute()
        )
        items = [_file_to_doc_info(f) for f in response.get("files", [])]
        return items, response.get("nextPageToken")

    items, _ = paginate(fetch_page, limit)
    return items


def create_doc(account: str, config: AppConfig, title: str, content: str) -> tuple[str, str]:
    service = _docs_service(account, config)
    try:
        document = service.documents().create(body={"title": title}).execute()
        if content:
            service.documents().batchUpdate(
                documentId=document["documentId"],
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
            ).execute()
    except Exception as exc:
        request_id = log_mutation(
            "docs.create",
            account,
            "doc",
            "unknown",
            "error",
            f"Create doc {title}",
            config,
            error=str(exc),
            params={"title": title},
        )
        raise click.ClickException(f"Failed to create doc | audit: {request_id}") from exc
    doc_id = document["documentId"]
    request_id = log_mutation(
        "docs.create",
        account,
        "doc",
        doc_id,
        "success",
        f"Create doc {title}",
        config,
        params={"title": title},
    )
    return doc_id, request_id


def update_doc(
    account: str,
    config: AppConfig,
    doc_id: str,
    content: str,
    mode: str,
) -> tuple[str, str]:
    service = _docs_service(account, config)
    try:
        if mode == "replace":
            document = service.documents().get(documentId=doc_id).execute()
            end_index = max(
                1,
                document.get("body", {}).get("content", [{}])[-1].get("endIndex", 1) - 1,
            )
            requests = []
            if end_index > 1:
                requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index}}})
            requests.append({"insertText": {"location": {"index": 1}, "text": content}})
        elif mode == "append":
            document = service.documents().get(documentId=doc_id).execute()
            end_index = max(
                1,
                document.get("body", {}).get("content", [{}])[-1].get("endIndex", 1) - 1,
            )
            requests = [{"insertText": {"location": {"index": end_index}, "text": content}}]
        else:
            raise click.UsageError(f"Unsupported mode: {mode}")
        service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    except Exception as exc:
        request_id = log_mutation(
            "docs.update",
            account,
            "doc",
            doc_id,
            "error",
            f"Update doc {doc_id} ({mode})",
            config,
            error=str(exc),
            params={"doc_id": doc_id, "mode": mode},
        )
        raise click.ClickException(f"Failed to update doc | audit: {request_id}") from exc
    request_id = log_mutation(
        "docs.update",
        account,
        "doc",
        doc_id,
        "success",
        f"Update doc {doc_id} ({mode})",
        config,
        params={"doc_id": doc_id, "mode": mode},
    )
    return doc_id, request_id
