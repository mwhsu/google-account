import click

try:
    from googleapiclient.discovery import build
except ImportError:  # pragma: no cover
    build = None

from src.audit import log_mutation
from src.auth import get_credentials
from src.config import AppConfig
from src.models import Contact
from src.pagination import paginate

PERSON_FIELDS = "names,emailAddresses,phoneNumbers,organizations"


def _people_service(account: str, config: AppConfig):
    if build is None:
        raise click.ClickException("google-api-python-client is not installed")
    return build("people", "v1", credentials=get_credentials(account, config))


def _person_to_model(person: dict) -> Contact:
    names = person.get("names", [])
    display_name = names[0].get("displayName", "") if names else ""
    emails = [e.get("value", "") for e in person.get("emailAddresses", []) if e.get("value")]
    phones = [p.get("value", "") for p in person.get("phoneNumbers", []) if p.get("value")]
    orgs = person.get("organizations", [])
    organization = orgs[0].get("name", "") if orgs else ""
    return Contact(
        resource_name=person.get("resourceName", ""),
        display_name=display_name,
        emails=emails,
        phones=phones,
        organization=organization,
    )


def list_contacts(
    account: str, config: AppConfig, limit: int
) -> list[Contact]:
    service = _people_service(account, config)

    def fetch_page(token):
        response = (
            service.people()
            .connections()
            .list(
                resourceName="people/me",
                pageSize=min(limit, 1000),
                pageToken=token,
                personFields=PERSON_FIELDS,
                sortOrder="LAST_MODIFIED_DESCENDING",
            )
            .execute()
        )
        items = [_person_to_model(p) for p in response.get("connections", [])]
        return items, response.get("nextPageToken")

    items, _ = paginate(fetch_page, limit)
    return items


def search_contacts(
    account: str, config: AppConfig, query: str
) -> list[Contact]:
    service = _people_service(account, config)
    response = (
        service.people()
        .searchContacts(
            query=query,
            readMask=PERSON_FIELDS,
        )
        .execute()
    )
    results = response.get("results", [])
    return [_person_to_model(r.get("person", {})) for r in results]


def get_contact(
    account: str, config: AppConfig, resource_name: str
) -> Contact:
    service = _people_service(account, config)
    person = (
        service.people()
        .get(resourceName=resource_name, personFields=PERSON_FIELDS)
        .execute()
    )
    return _person_to_model(person)


def create_contact(
    account: str,
    config: AppConfig,
    name: str,
    email: str | None = None,
    phone: str | None = None,
    organization: str | None = None,
) -> tuple[str, str]:
    service = _people_service(account, config)
    body: dict = {
        "names": [{"givenName": name}],
    }
    if email:
        body["emailAddresses"] = [{"value": email}]
    if phone:
        body["phoneNumbers"] = [{"value": phone}]
    if organization:
        body["organizations"] = [{"name": organization}]
    try:
        result = service.people().createContact(body=body).execute()
    except Exception as exc:
        request_id = log_mutation(
            "contacts.create",
            account,
            "contact",
            "unknown",
            "error",
            f"Create contact {name}",
            config,
            error=str(exc),
            params={"name": name},
        )
        raise click.ClickException(
            f"Failed to create contact | audit: {request_id}"
        ) from exc
    resource_name = result.get("resourceName", "")
    request_id = log_mutation(
        "contacts.create",
        account,
        "contact",
        resource_name,
        "success",
        f"Create contact {name}",
        config,
        params={"name": name},
    )
    return resource_name, request_id


def update_contact(
    account: str,
    config: AppConfig,
    resource_name: str,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    organization: str | None = None,
) -> tuple[str, str]:
    service = _people_service(account, config)
    # Fetch current contact to get etag for update
    current = (
        service.people()
        .get(resourceName=resource_name, personFields=PERSON_FIELDS)
        .execute()
    )
    etag = current.get("etag", "")
    update_fields = []
    body: dict = {"etag": etag}
    if name is not None:
        body["names"] = [{"givenName": name}]
        update_fields.append("names")
    if email is not None:
        body["emailAddresses"] = [{"value": email}]
        update_fields.append("emailAddresses")
    if phone is not None:
        body["phoneNumbers"] = [{"value": phone}]
        update_fields.append("phoneNumbers")
    if organization is not None:
        body["organizations"] = [{"name": organization}]
        update_fields.append("organizations")
    if not update_fields:
        raise click.UsageError("Specify at least one field to update (--name, --email, --phone, --org)")
    try:
        result = (
            service.people()
            .updateContact(
                resourceName=resource_name,
                body=body,
                updatePersonFields=",".join(update_fields),
            )
            .execute()
        )
    except Exception as exc:
        request_id = log_mutation(
            "contacts.update",
            account,
            "contact",
            resource_name,
            "error",
            f"Update contact {resource_name}",
            config,
            error=str(exc),
            params={"resource_name": resource_name},
        )
        raise click.ClickException(
            f"Failed to update contact | audit: {request_id}"
        ) from exc
    request_id = log_mutation(
        "contacts.update",
        account,
        "contact",
        resource_name,
        "success",
        f"Update contact {resource_name}",
        config,
        params={"resource_name": resource_name},
    )
    return resource_name, request_id


def delete_contact(
    account: str, config: AppConfig, resource_name: str
) -> tuple[str, str]:
    service = _people_service(account, config)
    try:
        service.people().deleteContact(resourceName=resource_name).execute()
    except Exception as exc:
        request_id = log_mutation(
            "contacts.delete",
            account,
            "contact",
            resource_name,
            "error",
            f"Delete contact {resource_name}",
            config,
            error=str(exc),
            params={"resource_name": resource_name},
        )
        raise click.ClickException(
            f"Failed to delete contact | audit: {request_id}"
        ) from exc
    request_id = log_mutation(
        "contacts.delete",
        account,
        "contact",
        resource_name,
        "success",
        f"Delete contact {resource_name}",
        config,
        params={"resource_name": resource_name},
    )
    return resource_name, request_id
