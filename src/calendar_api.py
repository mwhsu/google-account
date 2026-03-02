from datetime import datetime, timedelta, timezone

import click

try:
    from googleapiclient.discovery import build
except ImportError:  # pragma: no cover - exercised only in dependency-light test envs
    build = None

from src.audit import log_mutation
from src.auth import get_credentials
from src.config import AppConfig, get_calendar_id
from src.models import CalendarEvent
from src.pagination import paginate
from src.sanitizer import sanitize


def _calendar_service(account: str, config: AppConfig):
    if build is None:
        raise click.ClickException("google-api-python-client is not installed")
    return build("calendar", "v3", credentials=get_credentials(account, config))


def _event_to_model(event: dict, config: AppConfig) -> CalendarEvent:
    description = event.get("description", "")
    return CalendarEvent(
        id=event["id"],
        summary=event.get("summary", ""),
        start=event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", ""),
        end=event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", ""),
        location=event.get("location", ""),
        sanitized_description=sanitize(
            description,
            "CALENDAR_DESCRIPTION",
            config.sanitization.max_calendar_description_chars,
            strip_html=config.sanitization.strip_html,
            neutralize=config.sanitization.neutralize_injections,
        )
        if description
        else "",
        status=event.get("status", ""),
        html_link=event.get("htmlLink", ""),
    )


def _list_events(
    account: str,
    config: AppConfig,
    *,
    time_min: str,
    time_max: str,
    query: str | None = None,
    calendar: str | None = None,
    limit: int = 250,
):
    service = _calendar_service(account, config)
    cal_id = get_calendar_id(calendar, config)

    def fetch_page(token):
        response = (
            service.events()
            .list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                q=query,
                maxResults=min(limit, 250),
                pageToken=token,
            )
            .execute()
        )
        items = [_event_to_model(e, config) for e in response.get("items", [])]
        return items, response.get("nextPageToken")

    items, _ = paginate(fetch_page, limit)
    return items


def get_today(account: str, config: AppConfig, calendar: str | None = None) -> list[CalendarEvent]:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return _list_events(account, config, time_min=start.isoformat(), time_max=end.isoformat(), calendar=calendar)


def get_upcoming(account: str, config: AppConfig, days: int, calendar: str | None = None) -> list[CalendarEvent]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    return _list_events(account, config, time_min=start.isoformat(), time_max=end.isoformat(), calendar=calendar)


def search_events(
    account: str,
    config: AppConfig,
    query: str,
    days: int,
    calendar: str | None = None,
) -> list[CalendarEvent]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    return _list_events(
        account,
        config,
        time_min=start.isoformat(),
        time_max=end.isoformat(),
        query=query,
        calendar=calendar,
    )


def create_event(
    account: str,
    config: AppConfig,
    title: str,
    start: str,
    end: str,
    description: str,
    location: str,
    calendar: str | None = None,
) -> tuple[str, str]:
    service = _calendar_service(account, config)
    body = {
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        "description": description,
        "location": location,
    }
    try:
        event = service.events().insert(calendarId=get_calendar_id(calendar, config), body=body).execute()
    except Exception as exc:
        request_id = log_mutation(
            "calendar.create",
            account,
            "event",
            "unknown",
            "error",
            f"Create event {title}",
            config,
            error=str(exc),
            params={"title": title, "start": start, "end": end},
        )
        raise click.ClickException(f"Failed to create event | audit: {request_id}") from exc
    request_id = log_mutation(
        "calendar.create",
        account,
        "event",
        event["id"],
        "success",
        f"Create event {title}",
        config,
        params={"title": title, "start": start, "end": end},
    )
    return event["id"], request_id


def update_event(account: str, config: AppConfig, event_id: str, calendar: str | None = None, **kwargs) -> tuple[str, str]:
    service = _calendar_service(account, config)
    body = {}
    if kwargs.get("title") is not None:
        body["summary"] = kwargs["title"]
    if kwargs.get("start") is not None:
        body["start"] = {"dateTime": kwargs["start"]}
    if kwargs.get("end") is not None:
        body["end"] = {"dateTime": kwargs["end"]}
    if kwargs.get("description") is not None:
        body["description"] = kwargs["description"]
    if kwargs.get("location") is not None:
        body["location"] = kwargs["location"]
    changed_fields = {k: str(v) for k, v in kwargs.items() if v is not None}
    try:
        service.events().patch(calendarId=get_calendar_id(calendar, config), eventId=event_id, body=body).execute()
    except Exception as exc:
        request_id = log_mutation(
            "calendar.update",
            account,
            "event",
            event_id,
            "error",
            f"Update event {event_id}",
            config,
            error=str(exc),
            params={"event_id": event_id, **changed_fields},
        )
        raise click.ClickException(f"Failed to update event | audit: {request_id}") from exc
    request_id = log_mutation(
        "calendar.update",
        account,
        "event",
        event_id,
        "success",
        f"Update event {event_id}",
        config,
        params={"event_id": event_id, **changed_fields},
    )
    return event_id, request_id


def delete_event(account: str, config: AppConfig, event_id: str, calendar: str | None = None) -> tuple[str, str]:
    service = _calendar_service(account, config)
    try:
        service.events().delete(calendarId=get_calendar_id(calendar, config), eventId=event_id).execute()
    except Exception as exc:
        request_id = log_mutation(
            "calendar.delete",
            account,
            "event",
            event_id,
            "error",
            f"Delete event {event_id}",
            config,
            error=str(exc),
            params={"event_id": event_id},
        )
        raise click.ClickException(f"Failed to delete event | audit: {request_id}") from exc
    request_id = log_mutation(
        "calendar.delete",
        account,
        "event",
        event_id,
        "success",
        f"Delete event {event_id}",
        config,
        params={"event_id": event_id},
    )
    return event_id, request_id
