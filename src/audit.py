import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.config import AppConfig
from src.models import AuditEntry


def log_mutation(
    action: str,
    account: str,
    target_type: str,
    target_id: str,
    status: str,
    summary: str,
    config: AppConfig,
    error: str | None = None,
    params: dict[str, str] | None = None,
) -> str:
    request_id = f"req_{uuid.uuid4().hex[:16]}"
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        action=action,
        account=account,
        target_type=target_type,
        target_id=target_id,
        status=status,
        summary=summary,
        request_id=request_id,
        error=error,
        params=params,
    )
    path = Path(config.logging.audit_log_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")
    return request_id
