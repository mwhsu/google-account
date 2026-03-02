import json

import click

from src import auth as auth_api
from src import calendar_api, contacts_api, docs_api, drive_api, gmail, sheets_api
from src.config import load_config
from src.models import DraftInfo, SheetRange


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


@cli.group()
def drive():
    """List, search, download, upload, and manage Google Drive files."""


@cli.group()
def contacts():
    """List, search, and manage Google Contacts."""


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
@click.option("--thread-id")
@click.option("--in-reply-to")
@click.argument("to")
@_handle_errors
def gmail_draft(
    account: str, subject: str, body: str, thread_id: str | None, in_reply_to: str | None, to: str
):
    draft_id, request_id = gmail.create_draft(
        account, load_config(), to, subject, body, thread_id=thread_id, in_reply_to=in_reply_to
    )
    click.echo(f"✓ created draft | account: {account} | id: {draft_id} | audit: {request_id}")


@gmail_group.command("drafts")
@click.option("--account", required=True)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def gmail_drafts(account: str, limit: int, as_json: bool):
    _emit(gmail.list_drafts(account, load_config(), limit), as_json)


@gmail_group.command("delete-draft")
@click.option("--account", required=True)
@click.argument("draft_id")
@_handle_errors
def gmail_delete_draft(account: str, draft_id: str):
    deleted_id, request_id = gmail.delete_draft(account, load_config(), draft_id)
    click.echo(f"✓ deleted draft | account: {account} | id: {deleted_id} | audit: {request_id}")


@gmail_group.command("archive")
@click.option("--account", required=True)
@click.argument("message_id")
@_handle_errors
def gmail_archive(account: str, message_id: str):
    msg_id, request_id = gmail.archive_message(account, load_config(), message_id)
    click.echo(f"✓ archived | account: {account} | id: {msg_id} | audit: {request_id}")


@gmail_group.command("label")
@click.option("--account", required=True)
@click.option("--add", multiple=True)
@click.option("--remove", multiple=True)
@click.argument("message_id")
@_handle_errors
def gmail_label(account: str, add: tuple[str, ...], remove: tuple[str, ...], message_id: str):
    if not add and not remove:
        raise click.UsageError("Specify at least one --add or --remove label")
    msg_id, request_id = gmail.modify_labels(
        account, load_config(), message_id,
        add_labels=list(add) if add else None,
        remove_labels=list(remove) if remove else None,
    )
    click.echo(f"✓ labels modified | account: {account} | id: {msg_id} | audit: {request_id}")


@gmail_group.command("mark-read")
@click.option("--account", required=True)
@click.argument("message_id")
@_handle_errors
def gmail_mark_read(account: str, message_id: str):
    msg_id, request_id = gmail.mark_read(account, load_config(), message_id)
    click.echo(f"✓ marked read | account: {account} | id: {msg_id} | audit: {request_id}")


@gmail_group.command("mark-unread")
@click.option("--account", required=True)
@click.argument("message_id")
@_handle_errors
def gmail_mark_unread(account: str, message_id: str):
    msg_id, request_id = gmail.mark_unread(account, load_config(), message_id)
    click.echo(f"✓ marked unread | account: {account} | id: {msg_id} | audit: {request_id}")


@calendar.command("today")
@click.option("--account", required=True)
@click.option("--calendar", "calendar_alias")
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def calendar_today(account: str, calendar_alias: str | None, as_json: bool):
    _emit(calendar_api.get_today(account, load_config(), calendar=calendar_alias), as_json)


@calendar.command("upcoming")
@click.option("--account", required=True)
@click.option("--calendar", "calendar_alias")
@click.option("--days", default=7, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def calendar_upcoming(account: str, calendar_alias: str | None, days: int, as_json: bool):
    _emit(calendar_api.get_upcoming(account, load_config(), days, calendar=calendar_alias), as_json)


@calendar.command("search")
@click.option("--account", required=True)
@click.option("--calendar", "calendar_alias")
@click.option("--days", default=30, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.argument("query")
@_handle_errors
def calendar_search(account: str, calendar_alias: str | None, days: int, as_json: bool, query: str):
    _emit(calendar_api.search_events(account, load_config(), query, days, calendar=calendar_alias), as_json)


@calendar.command("create")
@click.option("--account", required=True)
@click.option("--calendar", "calendar_alias")
@click.option("--start", required=True)
@click.option("--end", required=True)
@click.option("--description", default="")
@click.option("--location", default="")
@click.argument("title")
@_handle_errors
def calendar_create(
    account: str,
    calendar_alias: str | None,
    start: str,
    end: str,
    description: str,
    location: str,
    title: str,
):
    event_id, request_id = calendar_api.create_event(
        account, load_config(), title, start, end, description, location, calendar=calendar_alias
    )
    click.echo(f"✓ created event | account: {account} | id: {event_id} | audit: {request_id}")


@calendar.command("update")
@click.option("--account", required=True)
@click.option("--calendar", "calendar_alias")
@click.option("--title")
@click.option("--start")
@click.option("--end")
@click.option("--description")
@click.option("--location")
@click.argument("event_id")
@_handle_errors
def calendar_update(
    account: str,
    calendar_alias: str | None,
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
        calendar=calendar_alias,
        title=title,
        start=start,
        end=end,
        description=description,
        location=location,
    )
    click.echo(f"✓ updated event | account: {account} | id: {updated_id} | audit: {request_id}")


@calendar.command("delete")
@click.option("--account", required=True)
@click.option("--calendar", "calendar_alias")
@click.argument("event_id")
@_handle_errors
def calendar_delete(account: str, calendar_alias: str | None, event_id: str):
    deleted_id, request_id = calendar_api.delete_event(account, load_config(), event_id, calendar=calendar_alias)
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


@docs.command("delete")
@click.option("--account", required=True)
@click.argument("doc_id")
@_handle_errors
def docs_delete(account: str, doc_id: str):
    trashed_id, request_id = drive_api.trash_file(account, load_config(), doc_id)
    click.echo(f"✓ trashed doc | account: {account} | id: {trashed_id} | audit: {request_id}")


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


@sheets.command("delete")
@click.option("--account", required=True)
@click.argument("sheet_id")
@_handle_errors
def sheets_delete(account: str, sheet_id: str):
    trashed_id, request_id = drive_api.trash_file(account, load_config(), sheet_id)
    click.echo(f"✓ trashed sheet | account: {account} | id: {trashed_id} | audit: {request_id}")


@drive.command("list")
@click.option("--account", required=True)
@click.option("--folder")
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def drive_list(account: str, folder: str | None, limit: int, as_json: bool):
    _emit(drive_api.list_files(account, load_config(), limit, folder=folder), as_json)


@drive.command("search")
@click.option("--account", required=True)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.argument("query")
@_handle_errors
def drive_search(account: str, limit: int, as_json: bool, query: str):
    _emit(drive_api.search_files(account, load_config(), query, limit), as_json)


@drive.command("get")
@click.option("--account", required=True)
@click.option("--json", "as_json", is_flag=True)
@click.argument("file_id")
@_handle_errors
def drive_get(account: str, as_json: bool, file_id: str):
    _emit(drive_api.get_file(account, load_config(), file_id), as_json)


@drive.command("download")
@click.option("--account", required=True)
@click.option("--output", "output_path")
@click.argument("file_id")
@_handle_errors
def drive_download(account: str, output_path: str | None, file_id: str):
    content, suggested_name = drive_api.download_file(account, load_config(), file_id)
    dest = output_path or suggested_name
    with open(dest, "wb") as f:
        f.write(content)
    click.echo(f"✓ downloaded | {len(content)} bytes | {dest}")


@drive.command("upload")
@click.option("--account", required=True)
@click.option("--folder")
@click.option("--name")
@click.argument("local_path")
@_handle_errors
def drive_upload(account: str, folder: str | None, name: str | None, local_path: str):
    file_id, request_id = drive_api.upload_file(
        account, load_config(), local_path, folder=folder, name=name
    )
    click.echo(f"✓ uploaded | account: {account} | id: {file_id} | audit: {request_id}")


@drive.command("create-folder")
@click.option("--account", required=True)
@click.option("--parent")
@click.argument("name")
@_handle_errors
def drive_create_folder(account: str, parent: str | None, name: str):
    folder_id, request_id = drive_api.create_folder(
        account, load_config(), name, parent=parent
    )
    click.echo(f"✓ created folder | account: {account} | id: {folder_id} | audit: {request_id}")


@drive.command("move")
@click.option("--account", required=True)
@click.option("--to", "destination", required=True)
@click.argument("file_id")
@_handle_errors
def drive_move(account: str, destination: str, file_id: str):
    moved_id, request_id = drive_api.move_file(account, load_config(), file_id, destination)
    click.echo(f"✓ moved | account: {account} | id: {moved_id} | audit: {request_id}")


@drive.command("rename")
@click.option("--account", required=True)
@click.option("--name", required=True)
@click.argument("file_id")
@_handle_errors
def drive_rename(account: str, name: str, file_id: str):
    renamed_id, request_id = drive_api.rename_file(account, load_config(), file_id, name)
    click.echo(f"✓ renamed | account: {account} | id: {renamed_id} | audit: {request_id}")


@drive.command("trash")
@click.option("--account", required=True)
@click.argument("file_id")
@_handle_errors
def drive_trash(account: str, file_id: str):
    trashed_id, request_id = drive_api.trash_file(account, load_config(), file_id)
    click.echo(f"✓ trashed | account: {account} | id: {trashed_id} | audit: {request_id}")


@drive.command("delete")
@click.option("--account", required=True)
@click.argument("file_id")
@_handle_errors
def drive_delete(account: str, file_id: str):
    deleted_id, request_id = drive_api.delete_file(account, load_config(), file_id)
    click.echo(f"✓ deleted | account: {account} | id: {deleted_id} | audit: {request_id}")


@drive.command("share")
@click.option("--account", required=True)
@click.option("--email", required=True)
@click.option("--role", required=True, type=click.Choice(["reader", "writer", "commenter"]))
@click.argument("file_id")
@_handle_errors
def drive_share(account: str, email: str, role: str, file_id: str):
    perm_id, request_id = drive_api.share_file(account, load_config(), file_id, email, role)
    click.echo(f"✓ shared | account: {account} | permission: {perm_id} | audit: {request_id}")


@drive.command("permissions")
@click.option("--account", required=True)
@click.option("--json", "as_json", is_flag=True)
@click.argument("file_id")
@_handle_errors
def drive_permissions(account: str, as_json: bool, file_id: str):
    _emit(drive_api.list_permissions(account, load_config(), file_id), as_json)


@contacts.command("list")
@click.option("--account", required=True)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@_handle_errors
def contacts_list(account: str, limit: int, as_json: bool):
    _emit(contacts_api.list_contacts(account, load_config(), limit), as_json)


@contacts.command("search")
@click.option("--account", required=True)
@click.option("--json", "as_json", is_flag=True)
@click.argument("query")
@_handle_errors
def contacts_search(account: str, as_json: bool, query: str):
    _emit(contacts_api.search_contacts(account, load_config(), query), as_json)


@contacts.command("get")
@click.option("--account", required=True)
@click.option("--json", "as_json", is_flag=True)
@click.argument("resource_name")
@_handle_errors
def contacts_get(account: str, as_json: bool, resource_name: str):
    _emit(contacts_api.get_contact(account, load_config(), resource_name), as_json)


@contacts.command("create")
@click.option("--account", required=True)
@click.option("--name", required=True)
@click.option("--email")
@click.option("--phone")
@click.option("--org")
@_handle_errors
def contacts_create(account: str, name: str, email: str | None, phone: str | None, org: str | None):
    resource_name, request_id = contacts_api.create_contact(
        account, load_config(), name, email=email, phone=phone, organization=org
    )
    click.echo(f"✓ created contact | account: {account} | id: {resource_name} | audit: {request_id}")


@contacts.command("update")
@click.option("--account", required=True)
@click.option("--name")
@click.option("--email")
@click.option("--phone")
@click.option("--org")
@click.argument("resource_name")
@_handle_errors
def contacts_update(
    account: str,
    name: str | None,
    email: str | None,
    phone: str | None,
    org: str | None,
    resource_name: str,
):
    updated_name, request_id = contacts_api.update_contact(
        account, load_config(), resource_name, name=name, email=email, phone=phone, organization=org
    )
    click.echo(f"✓ updated contact | account: {account} | id: {updated_name} | audit: {request_id}")


@contacts.command("delete")
@click.option("--account", required=True)
@click.argument("resource_name")
@_handle_errors
def contacts_delete(account: str, resource_name: str):
    deleted_name, request_id = contacts_api.delete_contact(account, load_config(), resource_name)
    click.echo(f"✓ deleted contact | account: {account} | id: {deleted_name} | audit: {request_id}")


@cli.command("doctor")
@_handle_errors
def doctor():
    """Check OAuth token health for all accounts."""
    config = load_config()
    all_healthy = True
    for alias in config.accounts:
        report = auth_api.check_token_health(alias, config)
        status = report["status"]
        if status == "healthy":
            click.echo(f"✓ {alias}: healthy")
        elif status == "not_authenticated":
            click.echo(f"✗ {alias}: not authenticated — run: google auth login {alias}")
            all_healthy = False
        elif status == "stale_scopes":
            missing = ", ".join(report["missing_scopes"])
            click.echo(f"✗ {alias}: missing scopes ({missing}) — run: google auth login {alias}")
            all_healthy = False
        elif status == "expired":
            click.echo(f"✗ {alias}: token expired — run: google auth login {alias}")
            all_healthy = False
        else:
            click.echo(f"✗ {alias}: {report.get('error', 'unknown issue')}")
            all_healthy = False
    if all_healthy:
        click.echo("\nAll accounts healthy.")
    else:
        click.echo("\nSome accounts need attention. Re-authenticate with: google auth login <alias>")


cli.add_command(gmail_group, name="gmail")
