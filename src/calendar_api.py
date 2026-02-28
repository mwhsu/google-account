from datetime import datetime, timedelta, timezone

import click
from googleapiclient.discovery import build

from src.audit import log_mutation
from src.auth import get_credentials
from src.config import AppConfig
from src.models import CalendarEvent
from src.sanitizer import sanitize


def _calendar_service(account: str, config: AppConfig):
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


def _list_events(account: str, config: AppConfig, *, time_min: str, time_max: str, query: str | None = None):
    service = _calendar_service(account, config)
    response = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            q=query,
        )
        .execute()
    )
    return [_event_to_model(event, config) for event in response.get("items", [])]


def get_today(account: str, config: AppConfig) -> list[CalendarEvent]:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return _list_events(account, config, time_min=start.isoformat(), time_max=end.isoformat())


def get_upcoming(account: str, config: AppConfig, days: int) -> list[CalendarEvent]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    return _list_events(account, config, time_min=start.isoformat(), time_max=end.isoformat())


def search_events(account: str, config: AppConfig, query: str, days: int) -> list[CalendarEvent]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    return _list_events(
        account,
        config,
        time_min=start.isoformat(),
        time_max=end.isoformat(),
        query=query,
    )


def create_event(
    account: str,
    config: AppConfig,
    title: str,
    start: str,
    end: str,
    description: str,
    location: str,
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
        event = service.events().insert(calendarId="primary", body=body).execute()
    except Exception as exc:
        request_id = log_mutation(
            "calendar.create_event",
            account,
            "event",
            "unknown",
            "error",
            f"Create event {title}",
            config,
            error=str(exc),
        )
        raise click.ClickException(f"Failed to create event | audit: {request_id}") from exc
    request_id = log_mutation(
        "calendar.create_event",
        account,
        "event",
        event["id"],
        "success",
        f"Create event {title}",
        config,
    )
    return event["id"], request_id


def update_event(account: str, config: AppConfig, event_id: str, **kwargs) -> tuple[str, str]:
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
    try:
        service.events().patch(calendarId="primary", eventId=event_id, body=body).execute()
    except Exception as exc:
        request_id = log_mutation(
            "calendar.update_event",
            account,
            "event",
            event_id,
            "error",
            f"Update event {event_id}",
            config,
            error=str(exc),
        )
        raise click.ClickException(f"Failed to update event | audit: {request_id}") from exc
    request_id = log_mutation(
        "calendar.update_event",
        account,
        "event",
        event_id,
        "success",
        f"Update event {event_id}",
        config,
    )
    return event_id, request_id


def delete_event(account: str, config: AppConfig, event_id: str) -> tuple[str, str]:
    service = _calendar_service(account, config)
    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
    except Exception as exc:
        request_id = log_mutation(
            "calendar.delete_event",
            account,
            "event",
            event_id,
            "error",
            f"Delete event {event_id}",
            config,
            error=str(exc),
        )
        raise click.ClickException(f"Failed to delete event | audit: {request_id}") from exc
    request_id = log_mutation(
        "calendar.delete_event",
        account,
        "event",
        event_id,
        "success",
        f"Delete event {event_id}",
        config,
    )
    return event_id, request_id
