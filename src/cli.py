import json

import click

from src import auth as auth_api
from src import calendar_api, docs_api, gmail, sheets_api
from src.config import load_config
from src.models import SheetRange


def _model_to_data(value):
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_model_to_data(item) for item in value]
    if isinstance(value, dict):
        return {key: _model_to_data(item) for key, item in value.items()}
    return value


def _emit(value, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(_model_to_data(value)))
        return
    if isinstance(value, list):
        for item in value:
            click.echo(item.model_dump_json() if hasattr(item, "model_dump_json") else json.dumps(item))
        return
    click.echo(value.model_dump_json(indent=2) if hasattr(value, "model_dump_json") else str(value))


def _emit_sheet(value, as_json: bool) -> None:
    if as_json or not isinstance(value, SheetRange):
        _emit(value, as_json)
        return
    click.echo(sheets_api.format_sheet_table(value))


def _handle_errors(func):
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except click.ClickException:
            raise
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

    wrapped.__name__ = func.__name__
    return wrapped


@click.group()
def cli():
    """Google account CLI - safe multi-account access."""


@cli.group()
def auth():
    """Manage OAuth2 authentication."""


@cli.group()
def gmail_group():
    """Read Gmail and create drafts."""


@cli.group()
def calendar():
    """Read and manage calendar events."""


@cli.group()
def docs():
    """Read and manage Google Docs."""


@cli.group()
def sheets():
    """Read and manage Google Sheets."""


@auth.command("login")
@click.argument("alias")
@_handle_errors
def auth_login(alias: str):
    config = load_config()
    auth_api.login(alias, config)
    click.echo(f"Authenticated account: {alias}")


@auth.command("list")
@_handle_errors
def auth_list():
    _emit(auth_api.list_accounts(load_config()), as_json=True)


@auth.command("remove")
@click.argument("alias")
@_handle_errors
def auth_remove(alias: str):
    config = load_config()
    auth_api.remove(alias, config)
    click.echo(f"Removed token for account: {alias}")


@gmail_group.command("inbox")
@click.option("--account", required=True)
@click.option("--unread", is_flag=True)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def gmail_inbox(account: str, unread: bool, limit: int, as_json: bool):
    _emit(gmail.get_inbox(account, load_config(), unread, limit), as_json)


@gmail_group.command("read")
@click.option("--account", required=True)
@click.option("--json", "as_json", is_flag=True)
@click.argument("message_id")
@_handle_errors
def gmail_read(account: str, as_json: bool, message_id: str):
    _emit(gmail.read_message(account, load_config(), message_id), as_json)


@gmail_group.command("search")
@click.option("--account", required=True)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.argument("query")
@_handle_errors
def gmail_search(account: str, limit: int, as_json: bool, query: str):
    _emit(gmail.search_messages(account, load_config(), query, limit), as_json)


@gmail_group.command("thread")
@click.option("--account", required=True)
@click.option("--json", "as_json", is_flag=True)
@click.argument("thread_id")
@_handle_errors
def gmail_thread(account: str, as_json: bool, thread_id: str):
    _emit(gmail.get_thread(account, load_config(), thread_id), as_json)


@gmail_group.command("labels")
@click.option("--account", required=True)
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def gmail_labels(account: str, as_json: bool):
    _emit(gmail.get_labels(account, load_config()), as_json)


@gmail_group.command("draft")
@click.option("--account", required=True)
@click.option("--subject", required=True)
@click.option("--body", required=True)
@click.argument("to")
@_handle_errors
def gmail_draft(account: str, subject: str, body: str, to: str):
    draft_id, request_id = gmail.create_draft(account, load_config(), to, subject, body)
    click.echo(f"✓ created draft | account: {account} | id: {draft_id} | audit: {request_id}")


@gmail_group.command("drafts")
@click.option("--account", required=True)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def gmail_drafts(account: str, limit: int, as_json: bool):
    _emit(gmail.list_drafts(account, load_config(), limit), as_json)


@calendar.command("today")
@click.option("--account", required=True)
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def calendar_today(account: str, as_json: bool):
    _emit(calendar_api.get_today(account, load_config()), as_json)


@calendar.command("upcoming")
@click.option("--account", required=True)
@click.option("--days", default=7, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def calendar_upcoming(account: str, days: int, as_json: bool):
    _emit(calendar_api.get_upcoming(account, load_config(), days), as_json)


@calendar.command("search")
@click.option("--account", required=True)
@click.option("--days", default=30, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.argument("query")
@_handle_errors
def calendar_search(account: str, days: int, as_json: bool, query: str):
    _emit(calendar_api.search_events(account, load_config(), query, days), as_json)


@calendar.command("create")
@click.option("--account", required=True)
@click.option("--start", required=True)
@click.option("--end", required=True)
@click.option("--description", default="")
@click.option("--location", default="")
@click.argument("title")
@_handle_errors
def calendar_create(
    account: str,
    start: str,
    end: str,
    description: str,
    location: str,
    title: str,
):
    event_id, request_id = calendar_api.create_event(
        account, load_config(), title, start, end, description, location
    )
    click.echo(f"✓ created event | account: {account} | id: {event_id} | audit: {request_id}")


@calendar.command("update")
@click.option("--account", required=True)
@click.option("--title")
@click.option("--start")
@click.option("--end")
@click.option("--description")
@click.option("--location")
@click.argument("event_id")
@_handle_errors
def calendar_update(
    account: str,
    title: str | None,
    start: str | None,
    end: str | None,
    description: str | None,
    location: str | None,
    event_id: str,
):
    updated_id, request_id = calendar_api.update_event(
        account,
        load_config(),
        event_id,
        title=title,
        start=start,
        end=end,
        description=description,
        location=location,
    )
    click.echo(f"✓ updated event | account: {account} | id: {updated_id} | audit: {request_id}")


@calendar.command("delete")
@click.option("--account", required=True)
@click.argument("event_id")
@_handle_errors
def calendar_delete(account: str, event_id: str):
    deleted_id, request_id = calendar_api.delete_event(account, load_config(), event_id)
    click.echo(f"✓ deleted event | account: {account} | id: {deleted_id} | audit: {request_id}")


@docs.command("list")
@click.option("--account", required=True)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def docs_list(account: str, limit: int, as_json: bool):
    _emit(docs_api.list_docs(account, load_config(), limit), as_json)


@docs.command("read")
@click.option("--account", required=True)
@click.option("--json", "as_json", is_flag=True)
@click.argument("doc_id")
@_handle_errors
def docs_read(account: str, as_json: bool, doc_id: str):
    _emit(docs_api.read_doc(account, load_config(), doc_id), as_json)


@docs.command("search")
@click.option("--account", required=True)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.argument("query")
@_handle_errors
def docs_search(account: str, limit: int, as_json: bool, query: str):
    _emit(docs_api.search_docs(account, load_config(), query, limit), as_json)


@docs.command("create")
@click.option("--account", required=True)
@click.option("--title", required=True)
@click.option("--content", default="")
@_handle_errors
def docs_create(account: str, title: str, content: str):
    doc_id, request_id = docs_api.create_doc(account, load_config(), title, content)
    click.echo(f"✓ created doc | account: {account} | id: {doc_id} | audit: {request_id}")


@docs.command("update")
@click.option("--account", required=True)
@click.option("--replace", "replace_content")
@click.option("--append", "append_content")
@click.argument("doc_id")
@_handle_errors
def docs_update(account: str, replace_content: str | None, append_content: str | None, doc_id: str):
    if (replace_content is None) == (append_content is None):
        raise click.UsageError("Specify exactly one of --replace or --append")
    mode = "replace" if replace_content is not None else "append"
    content = replace_content if replace_content is not None else append_content
    updated_id, request_id = docs_api.update_doc(account, load_config(), doc_id, content or "", mode)
    click.echo(f"✓ updated doc | account: {account} | id: {updated_id} | audit: {request_id}")


@sheets.command("list")
@click.option("--account", required=True)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def sheets_list(account: str, limit: int, as_json: bool):
    _emit(sheets_api.list_sheets(account, load_config(), limit), as_json)


@sheets.command("read")
@click.option("--account", required=True)
@click.option("--range", "range_name", default="Sheet1", show_default=True)
@click.option("--json", "as_json", is_flag=True)
@click.argument("sheet_id")
@_handle_errors
def sheets_read(account: str, range_name: str, as_json: bool, sheet_id: str):
    _emit_sheet(sheets_api.read_sheet(account, load_config(), sheet_id, range_name), as_json)


@sheets.command("search")
@click.option("--account", required=True)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.argument("query")
@_handle_errors
def sheets_search(account: str, limit: int, as_json: bool, query: str):
    _emit(sheets_api.search_sheets(account, load_config(), query, limit), as_json)


@sheets.command("create")
@click.option("--account", required=True)
@click.option("--title", required=True)
@click.option("--rows", default=1000, show_default=True, type=int)
@click.option("--cols", default=26, show_default=True, type=int)
@_handle_errors
def sheets_create(account: str, title: str, rows: int, cols: int):
    sheet_id, request_id = sheets_api.create_sheet(account, load_config(), title, rows, cols)
    click.echo(f"✓ created sheet | account: {account} | id: {sheet_id} | audit: {request_id}")


@sheets.command("update")
@click.option("--account", required=True)
@click.option("--range", "range_name", required=True)
@click.option("--values", required=True)
@click.argument("sheet_id")
@_handle_errors
def sheets_update(account: str, range_name: str, values: str, sheet_id: str):
    try:
        parsed_values = json.loads(values)
    except json.JSONDecodeError as exc:
        raise click.UsageError(f"--values must be valid JSON: {exc.msg}") from exc
    if not isinstance(parsed_values, list) or any(not isinstance(row, list) for row in parsed_values):
        raise click.UsageError("--values must decode to a JSON array of rows, e.g. [[\"a1\", \"b1\"]]")
    updated_id, request_id = sheets_api.update_sheet(
        account, load_config(), sheet_id, range_name, parsed_values
    )
    click.echo(f"✓ updated sheet | account: {account} | id: {updated_id} | audit: {request_id}")


cli.add_command(gmail_group, name="gmail")
