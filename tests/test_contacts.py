import pytest

from src import contacts_api
from src.config import AppConfig


def make_config(tmp_path):
    return AppConfig.model_validate(
        {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "accounts": {"personal": {"description": "Personal"}},
            "logging": {"audit_log_path": str(tmp_path / "audit.jsonl")},
        }
    )


class ExecuteWrapper:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeConnections:
    def __init__(self, list_payload=None):
        self.list_payload = list_payload or {"connections": []}
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return ExecuteWrapper(self.list_payload)


class FakePeople:
    def __init__(self, connections=None, get_payload=None, search_payload=None,
                 create_payload=None, update_payload=None, delete_payload=None):
        self._connections = connections or FakeConnections()
        self.get_payload = get_payload or person_payload()
        self.search_payload = search_payload or {"results": []}
        self.create_payload = create_payload or {"resourceName": "people/c123"}
        self.update_payload = update_payload or {"resourceName": "people/c123"}
        self.delete_payload = delete_payload or {}
        self.calls = []

    def connections(self):
        return self._connections

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return ExecuteWrapper(self.get_payload)

    def searchContacts(self, **kwargs):
        self.calls.append(("searchContacts", kwargs))
        return ExecuteWrapper(self.search_payload)

    def createContact(self, **kwargs):
        self.calls.append(("createContact", kwargs))
        return ExecuteWrapper(self.create_payload)

    def updateContact(self, **kwargs):
        self.calls.append(("updateContact", kwargs))
        return ExecuteWrapper(self.update_payload)

    def deleteContact(self, **kwargs):
        self.calls.append(("deleteContact", kwargs))
        return ExecuteWrapper(self.delete_payload)


class FakePeopleService:
    def __init__(self, people):
        self._people = people

    def people(self):
        return self._people


def person_payload(resource_name="people/c123", name="Jane Doe",
                   email="jane@example.com", phone="+1234567890", org="Acme"):
    return {
        "resourceName": resource_name,
        "etag": "etag-abc",
        "names": [{"displayName": name, "givenName": name}],
        "emailAddresses": [{"value": email}],
        "phoneNumbers": [{"value": phone}],
        "organizations": [{"name": org}],
    }


def test_list_contacts_returns_models(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    connections = FakeConnections(
        list_payload={"connections": [person_payload()]}
    )
    people = FakePeople(connections=connections)
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    result = contacts_api.list_contacts("personal", config, 10)

    assert result[0].display_name == "Jane Doe"
    assert result[0].emails == ["jane@example.com"]
    assert result[0].phones == ["+1234567890"]
    assert result[0].organization == "Acme"


def test_list_contacts_respects_limit(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    connections = FakeConnections(
        list_payload={"connections": [person_payload(), person_payload(resource_name="people/c456")]}
    )
    people = FakePeople(connections=connections)
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    result = contacts_api.list_contacts("personal", config, 1)

    assert len(result) == 1


def test_search_contacts_passes_query(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    people = FakePeople(
        search_payload={"results": [{"person": person_payload()}]}
    )
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    result = contacts_api.search_contacts("personal", config, "Jane")

    assert result[0].display_name == "Jane Doe"
    search_call = [c for c in people.calls if c[0] == "searchContacts"][0]
    assert search_call[1]["query"] == "Jane"


def test_get_contact_returns_model(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    people = FakePeople(get_payload=person_payload())
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    result = contacts_api.get_contact("personal", config, "people/c123")

    assert result.resource_name == "people/c123"
    assert result.display_name == "Jane Doe"


def test_create_contact_audit_logs(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    people = FakePeople(create_payload={"resourceName": "people/c789"})
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    resource_name, request_id = contacts_api.create_contact(
        "personal", config, "Bob", email="bob@example.com", phone="+1111111111"
    )

    assert resource_name == "people/c789"
    assert request_id.startswith("req_")
    assert "contacts.create" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    create_call = [c for c in people.calls if c[0] == "createContact"][0]
    assert create_call[1]["body"]["names"][0]["givenName"] == "Bob"
    assert create_call[1]["body"]["emailAddresses"][0]["value"] == "bob@example.com"


def test_create_contact_with_org(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    people = FakePeople(create_payload={"resourceName": "people/c789"})
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    contacts_api.create_contact("personal", config, "Bob", organization="Acme Inc")

    create_call = [c for c in people.calls if c[0] == "createContact"][0]
    assert create_call[1]["body"]["organizations"][0]["name"] == "Acme Inc"


def test_update_contact_fetches_etag_and_patches(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    people = FakePeople(
        get_payload=person_payload(),
        update_payload={"resourceName": "people/c123"},
    )
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    resource_name, request_id = contacts_api.update_contact(
        "personal", config, "people/c123", name="Jane Smith"
    )

    assert resource_name == "people/c123"
    update_call = [c for c in people.calls if c[0] == "updateContact"][0]
    assert update_call[1]["body"]["etag"] == "etag-abc"
    assert update_call[1]["body"]["names"][0]["givenName"] == "Jane Smith"
    assert update_call[1]["updatePersonFields"] == "names"
    assert "contacts.update" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_update_contact_requires_at_least_one_field(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    people = FakePeople(get_payload=person_payload())
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    with pytest.raises(Exception, match="Specify at least one field"):
        contacts_api.update_contact("personal", config, "people/c123")


def test_delete_contact_audit_logs(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    people = FakePeople()
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    resource_name, request_id = contacts_api.delete_contact("personal", config, "people/c123")

    assert resource_name == "people/c123"
    assert any(c[0] == "deleteContact" for c in people.calls)
    assert "contacts.delete" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_mutation_failure_is_audit_logged(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    people = FakePeople(create_payload=RuntimeError("boom"))
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    with pytest.raises(Exception):
        contacts_api.create_contact("personal", config, "Bob")

    assert '"status":"error"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_person_with_missing_fields_returns_defaults(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    # Minimal person with only resourceName
    minimal = {"resourceName": "people/c999"}
    people = FakePeople(get_payload=minimal)
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    result = contacts_api.get_contact("personal", config, "people/c999")

    assert result.resource_name == "people/c999"
    assert result.display_name == ""
    assert result.emails == []
    assert result.phones == []
    assert result.organization == ""


class PaginatedFakeConnections:
    """FakeConnections that returns different pages on successive list() calls."""

    def __init__(self, pages):
        self.pages = pages
        self.call_index = 0
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        page = self.pages[self.call_index]
        self.call_index += 1
        return ExecuteWrapper(page)


def test_list_contacts_paginates_across_pages(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = [
        {"connections": [person_payload("people/c1", "Alice")], "nextPageToken": "tok2"},
        {"connections": [person_payload("people/c2", "Bob")]},
    ]
    connections = PaginatedFakeConnections(pages)
    people = FakePeople(connections=connections)
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    result = contacts_api.list_contacts("personal", config, 10)

    assert len(result) == 2
    assert result[0].display_name == "Alice"
    assert result[1].display_name == "Bob"
    assert connections.calls[1][1]["pageToken"] == "tok2"


def test_list_contacts_stops_at_limit(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = [
        {"connections": [person_payload("people/c1"), person_payload("people/c2")], "nextPageToken": "tok2"},
    ]
    connections = PaginatedFakeConnections(pages)
    people = FakePeople(connections=connections)
    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", lambda *_args, **_kwargs: FakePeopleService(people))

    result = contacts_api.list_contacts("personal", config, 1)

    assert len(result) == 1
    assert len(connections.calls) == 1


def test_all_functions_use_mocked_google_api_client(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    calls = []

    def fake_build(*args, **kwargs):
        calls.append((args, kwargs))
        return FakePeopleService(FakePeople(
            connections=FakeConnections(list_payload={"connections": [person_payload()]})
        ))

    monkeypatch.setattr(contacts_api, "get_credentials", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(contacts_api, "build", fake_build)

    contacts_api.list_contacts("personal", config, 10)

    assert calls[0][0][:2] == ("people", "v1")
