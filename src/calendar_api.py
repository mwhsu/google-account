from datetime import date, datetime, timedelta, timezone

import click

try:
    from googleapiclient.discovery import build
except ImportError:  # pragma: no cover - exercised only in dependency-light test envs
    build = None

from src.audit import log_mutation
from src.auth import get_credentials
from src.config import AppConfig, get_account, get_calendar_id
from src.models import (
    AccountFreeBusy,
    CalendarEvent,
    CalendarFreeBusyResult,
    CalendarOverlapResult,
    CalendarWindow,
)
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


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _merge_windows(windows: list[CalendarWindow]) -> list[CalendarWindow]:
    if not windows:
        return []
    ordered = sorted(windows, key=lambda window: window.start)
    merged = [ordered[0]]
    for window in ordered[1:]:
        previous = merged[-1]
        if _parse_datetime(window.start) <= _parse_datetime(previous.end):
            merged[-1] = CalendarWindow(
                start=previous.start,
                end=max(previous.end, window.end, key=_parse_datetime),
            )
            continue
        merged.append(window)
    return merged


def _invert_busy_windows(
    busy_windows: list[CalendarWindow],
    day_start: datetime,
    day_end: datetime,
) -> list[CalendarWindow]:
    free_windows: list[CalendarWindow] = []
    cursor = day_start
    for window in busy_windows:
        window_start = _parse_datetime(window.start)
        window_end = _parse_datetime(window.end)
        if window_start > cursor:
            free_windows.append(CalendarWindow(start=cursor.isoformat(), end=window_start.isoformat()))
        if window_end > cursor:
            cursor = window_end
    if cursor < day_end:
        free_windows.append(CalendarWindow(start=cursor.isoformat(), end=day_end.isoformat()))
    return free_windows


def _day_bounds(value: str) -> tuple[datetime, datetime]:
    target_day = date.fromisoformat(value)
    start = datetime(target_day.year, target_day.month, target_day.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _resolve_freebusy_calendar_id(requester: str, target_account: str, config: AppConfig) -> str:
    if requester == target_account:
        return "primary"
    calendar_id = get_account(target_account, config).calendar_id
    if not calendar_id:
        raise click.UsageError(
            f"Account '{target_account}' requires accounts.{target_account}.calendar_id for cross-account free/busy"
        )
    return calendar_id


def _list_events(
    account: str,
    config: AppConfig,
    *,
    time_min: str,
    time_max: str,
    query: str | None = None,
    calendar: str | None = None,
):
    service = _calendar_service(account, config)
    response = (
        service.events()
        .list(
            calendarId=get_calendar_id(calendar, config),
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            q=query,
        )
        .execute()
    )
    return [_event_to_model(event, config) for event in response.get("items", [])]


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
    )
    return event_id, request_id


def get_free_busy(accounts: list[str], config: AppConfig, target_date: str) -> CalendarFreeBusyResult:
    if not accounts:
        raise click.UsageError("Specify at least one account")
    requester = accounts[0]
    day_start, day_end = _day_bounds(target_date)
    calendar_ids = {
        account: _resolve_freebusy_calendar_id(requester, account, config) for account in accounts
    }
    service = _calendar_service(requester, config)
    response = (
        service.freebusy()
        .query(
            body={
                "timeMin": day_start.isoformat(),
                "timeMax": day_end.isoformat(),
                "items": [{"id": calendar_id} for calendar_id in calendar_ids.values()],
            }
        )
        .execute()
    )
    calendars = response.get("calendars", {})
    schedules: list[AccountFreeBusy] = []
    merged_windows: list[CalendarWindow] = []
    for account in accounts:
        busy = [
            CalendarWindow(start=window["start"], end=window["end"])
            for window in calendars.get(calendar_ids[account], {}).get("busy", [])
        ]
        schedules.append(AccountFreeBusy(account=account, busy=busy))
        merged_windows.extend(busy)
    merged_busy = _merge_windows(merged_windows)
    merged_free = _invert_busy_windows(merged_busy, day_start, day_end)
    return CalendarFreeBusyResult(
        date=target_date,
        accounts=schedules,
        merged_busy=merged_busy,
        merged_free=merged_free,
    )


def get_overlap(
    accounts: list[str],
    config: AppConfig,
    target_date: str,
    min_duration_minutes: int,
) -> CalendarOverlapResult:
    free_busy = get_free_busy(accounts, config, target_date)
    windows = []
    minimum = timedelta(minutes=min_duration_minutes)
    for window in free_busy.merged_free:
        duration = _parse_datetime(window.end) - _parse_datetime(window.start)
        if duration >= minimum:
            windows.append(window)
    return CalendarOverlapResult(
        date=target_date,
        accounts=accounts,
        min_duration_minutes=min_duration_minutes,
        windows=windows,
    )
