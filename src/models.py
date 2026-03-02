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


class DraftInfo(BaseModel):
    id: str
    message_id: str
    subject: str = ""
    to: str = ""


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


class DriveFile(BaseModel):
    id: str
    name: str
    mime_type: str = ""
    modified_time: str = ""
    size: str = ""
    parents: list[str] = []
    web_view_link: str = ""
    trashed: bool = False


class DrivePermission(BaseModel):
    id: str
    role: str
    type: str
    email_address: str = ""
    display_name: str = ""


class DriveFolder(BaseModel):
    id: str
    name: str
    parents: list[str] = []


class Contact(BaseModel):
    resource_name: str
    display_name: str = ""
    emails: list[str] = []
    phones: list[str] = []
    organization: str = ""


class ContactGroup(BaseModel):
    resource_name: str
    name: str
    member_count: int = 0


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
    params: dict[str, str] | None = None
