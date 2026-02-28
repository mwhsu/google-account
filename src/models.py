from pydantic import BaseModel


class EmailMessage(BaseModel):
    id: str
    thread_id: str
    subject: str
    sender: str
    to: str
    date: str
    snippet: str
    sanitized_body: str
    labels: list[str] = []


class EmailThread(BaseModel):
    id: str
    subject: str
    messages: list[EmailMessage]


class CalendarEvent(BaseModel):
    id: str
    summary: str
    start: str
    end: str
    location: str = ""
    sanitized_description: str = ""
    status: str = ""
    html_link: str = ""


class Label(BaseModel):
    id: str
    name: str
    type: str = ""


class AuditEntry(BaseModel):
    timestamp: str
    action: str
    account: str
    target_type: str
    target_id: str
    status: str
    summary: str
    request_id: str
    error: str | None = None
