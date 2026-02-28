import base64
from email.mime.text import MIMEText

import click
from googleapiclient.discovery import build

from src.audit import log_mutation
from src.auth import get_credentials
from src.config import AppConfig
from src.models import EmailMessage, EmailThread, Label
from src.sanitizer import sanitize


def _gmail_service(account: str, config: AppConfig):
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
    response = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["INBOX"], q=query, maxResults=limit)
        .execute()
    )
    messages = []
    for item in response.get("messages", []):
        message = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
        messages.append(_to_email_message(message, config))
    return messages


def read_message(account: str, config: AppConfig, message_id: str) -> EmailMessage:
    service = _gmail_service(account, config)
    message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    return _to_email_message(message, config)


def search_messages(account: str, config: AppConfig, query: str, limit: int) -> list[EmailMessage]:
    service = _gmail_service(account, config)
    response = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
    messages = []
    for item in response.get("messages", []):
        message = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
        messages.append(_to_email_message(message, config))
    return messages


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


def create_draft(account: str, config: AppConfig, to: str, subject: str, body: str) -> tuple[str, str]:
    service = _gmail_service(account, config)
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    try:
        response = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": encoded}})
            .execute()
        )
    except Exception as exc:
        request_id = log_mutation(
            "gmail.create_draft",
            account,
            "draft",
            "unknown",
            "error",
            f"Create draft for {to}",
            config,
            error=str(exc),
        )
        raise click.ClickException(f"Failed to create draft | audit: {request_id}") from exc
    draft_id = response["id"]
    request_id = log_mutation(
        "gmail.create_draft",
        account,
        "draft",
        draft_id,
        "success",
        f"Create draft for {to}",
        config,
    )
    return draft_id, request_id


def list_drafts(account: str, config: AppConfig, limit: int) -> list[dict]:
    service = _gmail_service(account, config)
    response = service.users().drafts().list(userId="me", maxResults=limit).execute()
    drafts = []
    for draft in response.get("drafts", []):
        drafts.append({"id": draft["id"], "message_id": draft.get("message", {}).get("id", "")})
    return drafts
