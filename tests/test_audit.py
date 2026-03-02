import json

from src.audit import log_mutation
from src.config import AppConfig


def make_config(tmp_path):
    return AppConfig.model_validate(
        {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "accounts": {},
            "logging": {"audit_log_path": str(tmp_path / "logs" / "audit.jsonl")},
        }
    )


def read_entries(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_successful_mutation_writes_entry(tmp_path):
    config = make_config(tmp_path)

    request_id = log_mutation("action", "personal", "draft", "123", "success", "summary", config)

    entries = read_entries(tmp_path / "logs" / "audit.jsonl")
    assert entries[0]["request_id"] == request_id
    assert entries[0]["status"] == "success"


def test_failed_mutation_writes_error_field(tmp_path):
    config = make_config(tmp_path)

    log_mutation("action", "personal", "draft", "123", "error", "summary", config, error="boom")

    entries = read_entries(tmp_path / "logs" / "audit.jsonl")
    assert entries[0]["error"] == "boom"


def test_entry_contains_required_fields(tmp_path):
    config = make_config(tmp_path)

    log_mutation("action", "personal", "draft", "123", "success", "summary", config)

    entry = read_entries(tmp_path / "logs" / "audit.jsonl")[0]
    assert sorted(entry.keys()) == sorted(
        [
            "timestamp",
            "action",
            "account",
            "target_type",
            "target_id",
            "status",
            "summary",
            "request_id",
            "error",
            "params",
        ]
    )


def test_entries_are_append_only(tmp_path):
    config = make_config(tmp_path)

    log_mutation("action1", "personal", "draft", "123", "success", "summary", config)
    log_mutation("action2", "personal", "draft", "456", "success", "summary", config)

    entries = read_entries(tmp_path / "logs" / "audit.jsonl")
    assert len(entries) == 2
    assert entries[0]["action"] == "action1"
    assert entries[1]["action"] == "action2"


def test_parent_directories_are_created_automatically(tmp_path):
    config = make_config(tmp_path)

    log_mutation("action", "personal", "draft", "123", "success", "summary", config)

    assert (tmp_path / "logs" / "audit.jsonl").exists()


def test_request_id_matches_log_entry(tmp_path):
    config = make_config(tmp_path)

    request_id = log_mutation("action", "personal", "draft", "123", "success", "summary", config)

    entry = read_entries(tmp_path / "logs" / "audit.jsonl")[0]
    assert entry["request_id"] == request_id
