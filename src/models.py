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


class CalendarWindow(BaseModel):
    start: str
    end: str


class AccountFreeBusy(BaseModel):
    account: str
    busy: list[CalendarWindow]


class CalendarFreeBusyResult(BaseModel):
    date: str
    accounts: list[AccountFreeBusy]
    merged_busy: list[CalendarWindow]
    merged_free: list[CalendarWindow]


class CalendarOverlapResult(BaseModel):
    date: str
    accounts: list[str]
    min_duration_minutes: int
    windows: list[CalendarWindow]


class Label(BaseModel):
    id: str
    name: str
    type: str = ""


class DocInfo(BaseModel):
    id: str
    title: str
    modified_time: str = ""


class DocContent(BaseModel):
    id: str
    title: str
    sanitized_content: str


class SheetInfo(BaseModel):
    id: str
    title: str
    modified_time: str = ""


class SheetRange(BaseModel):
    spreadsheet_id: str
    range: str
    sanitized_range: str
    sanitized_values: list[list[str]]


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
