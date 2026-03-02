import base64
from email.mime.text import MIMEText

import click

try:
    from googleapiclient.discovery import build
except ImportError:  # pragma: no cover - exercised only in dependency-light test envs
    build = None

from src.audit import log_mutation
from src.auth import get_credentials
from src.config import AppConfig
from src.models import DraftInfo, EmailMessage, EmailThread, Label
from src.pagination import paginate
from src.sanitizer import sanitize


def _gmail_service(account: str, config: AppConfig):
    if build is None:
        raise click.ClickException("google-api-python-client is not installed")
    return build("gmail", "v1", credentials=get_credentials(account, config))


def _decode_body(data: str | None) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")


def _find_body(payload: dict) -> tuple[str, bool]:
    mime_type = payload.get("mimeType", "")
    body = _decode_body(payload.get("body", {}).get("data"))
    if mime_type == "text/plain" and body:
        return body, False
    if mime_type == "text/html" and body:
        return body, True
    for part in payload.get("parts", []):
        found_body, is_html = _find_body(part)
        if found_body:
            return found_body, is_html
    return body, mime_type == "text/html"


def _header(headers: list[dict], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _to_email_message(message: dict, config: AppConfig) -> EmailMessage:
    payload = message.get("payload", {})
    raw_body, is_html = _find_body(payload)
    sanitized_body = sanitize(
        raw_body,
        "EMAIL_BODY",
        config.sanitization.max_email_body_chars,
        strip_html=config.sanitization.strip_html or is_html,
        neutralize=config.sanitization.neutralize_injections,
    )
    headers = payload.get("headers", [])
    return EmailMessage(
        id=message["id"],
        thread_id=message.get("threadId", ""),
        subject=_header(headers, "Subject"),
        sender=_header(headers, "From"),
        to=_header(headers, "To"),
        date=_header(headers, "Date"),
        snippet=message.get("snippet", ""),
        sanitized_body=sanitized_body,
        labels=message.get("labelIds", []),
    )


def get_inbox(account: str, config: AppConfig, unread: bool, limit: int) -> list[EmailMessage]:
    service = _gmail_service(account, config)
    query = "is:unread" if unread else None

    def fetch_page(token):
        response = (
            service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], q=query, maxResults=min(limit, 100), pageToken=token)
            .execute()
        )
        items = []
        for item in response.get("messages", []):
            message = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
            items.append(_to_email_message(message, config))
        return items, response.get("nextPageToken")

    items, _ = paginate(fetch_page, limit)
    return items


def read_message(account: str, config: AppConfig, message_id: str) -> EmailMessage:
    service = _gmail_service(account, config)
    message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    return _to_email_message(message, config)


def search_messages(account: str, config: AppConfig, query: str, limit: int) -> list[EmailMessage]:
    service = _gmail_service(account, config)

    def fetch_page(token):
        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=min(limit, 100), pageToken=token)
            .execute()
        )
        items = []
        for item in response.get("messages", []):
            message = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
            items.append(_to_email_message(message, config))
        return items, response.get("nextPageToken")

    items, _ = paginate(fetch_page, limit)
    return items


def get_thread(account: str, config: AppConfig, thread_id: str) -> EmailThread:
    service = _gmail_service(account, config)
    thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    messages = [_to_email_message(message, config) for message in thread.get("messages", [])]
    subject = messages[0].subject if messages else ""
    return EmailThread(id=thread_id, subject=subject, messages=messages)


def get_labels(account: str, config: AppConfig) -> list[Label]:
    service = _gmail_service(account, config)
    response = service.users().labels().list(userId="me").execute()
    return [Label.model_validate(label) for label in response.get("labels", [])]


def create_draft(
    account: str,
    config: AppConfig,
    to: str,
    subject: str,
    body: str,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
) -> tuple[str, str]:
    service = _gmail_service(account, config)
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = in_reply_to
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    draft_body: dict = {"message": {"raw": encoded}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id
    try:
        response = (
            service.users()
            .drafts()
            .create(userId="me", body=draft_body)
            .execute()
        )
    except Exception as exc:
        request_id = log_mutation(
            "gmail.draft",
            account,
            "draft",
            "unknown",
            "error",
            f"Create draft for {to}",
            config,
            error=str(exc),
            params={"to": to, "subject": subject},
        )
        raise click.ClickException(f"Failed to create draft | audit: {request_id}") from exc
    draft_id = response["id"]
    request_id = log_mutation(
        "gmail.draft",
        account,
        "draft",
        draft_id,
        "success",
        f"Create draft for {to}",
        config,
        params={"to": to, "subject": subject},
    )
    return draft_id, request_id


def delete_draft(account: str, config: AppConfig, draft_id: str) -> tuple[str, str]:
    service = _gmail_service(account, config)
    try:
        service.users().drafts().delete(userId="me", id=draft_id).execute()
    except Exception as exc:
        request_id = log_mutation(
            "gmail.delete_draft",
            account,
            "draft",
            draft_id,
            "error",
            f"Delete draft {draft_id}",
            config,
            error=str(exc),
            params={"draft_id": draft_id},
        )
        raise click.ClickException(f"Failed to delete draft | audit: {request_id}") from exc
    request_id = log_mutation(
        "gmail.delete_draft",
        account,
        "draft",
        draft_id,
        "success",
        f"Delete draft {draft_id}",
        config,
        params={"draft_id": draft_id},
    )
    return draft_id, request_id


def archive_message(account: str, config: AppConfig, message_id: str) -> tuple[str, str]:
    return modify_labels(account, config, message_id, remove_labels=["INBOX"])


def modify_labels(
    account: str,
    config: AppConfig,
    message_id: str,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> tuple[str, str]:
    service = _gmail_service(account, config)
    body: dict = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels
    try:
        service.users().messages().modify(userId="me", id=message_id, body=body).execute()
    except Exception as exc:
        request_id = log_mutation(
            "gmail.modify_labels",
            account,
            "message",
            message_id,
            "error",
            f"Modify labels on {message_id}",
            config,
            error=str(exc),
            params={"message_id": message_id},
        )
        raise click.ClickException(f"Failed to modify labels | audit: {request_id}") from exc
    request_id = log_mutation(
        "gmail.modify_labels",
        account,
        "message",
        message_id,
        "success",
        f"Modify labels on {message_id}",
        config,
        params={"message_id": message_id},
    )
    return message_id, request_id


def mark_read(account: str, config: AppConfig, message_id: str) -> tuple[str, str]:
    return modify_labels(account, config, message_id, remove_labels=["UNREAD"])


def mark_unread(account: str, config: AppConfig, message_id: str) -> tuple[str, str]:
    return modify_labels(account, config, message_id, add_labels=["UNREAD"])


def list_drafts(account: str, config: AppConfig, limit: int) -> list[DraftInfo]:
    service = _gmail_service(account, config)

    def fetch_page(token):
        response = (
            service.users()
            .drafts()
            .list(userId="me", maxResults=min(limit, 100), pageToken=token)
            .execute()
        )
        raw_drafts = response.get("drafts", [])
        items = []
        for d in raw_drafts:
            detail = service.users().drafts().get(
                userId="me", id=d["id"], format="metadata",
            ).execute()
            message = detail.get("message", {})
            headers = message.get("payload", {}).get("headers", [])
            items.append(DraftInfo(
                id=detail["id"],
                message_id=message.get("id", ""),
                subject=_header(headers, "Subject"),
                to=_header(headers, "To"),
            ))
        return items, response.get("nextPageToken")

    items, _ = paginate(fetch_page, limit)
    return items
