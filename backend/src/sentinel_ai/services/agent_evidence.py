"""Building model evidence from stored records (Stage 11).

Every excerpt has a platform-generated id and an allow-listed kind; log text is read only
through ``runs.read_evidence`` (project grant, hash re-check, audited like a download), then
goes through the gateway's redactor before it leaves the platform. Nothing here reads files,
runs code or contacts a target."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from sentinel_ai.agents.common import token
from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.integrations.llm import evidence_filter as ef
from sentinel_ai.repositories import findings as findings_repo
from sentinel_ai.repositories import runs as runs_repo
from sentinel_ai.repositories.agent_context import ScopedResult
from sentinel_ai.repositories.findings import FindingRecord
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.services import runs as runs_service
from sentinel_ai.services.audit import RequestContext

MAX_CASES = 15
MAX_LOGS = 2
LOG_ITEM_CHARS = 3500
_FINDING_FIELDS = (
    "title",
    "category",
    "detected_by",
    "rule_id",
    "file_path",
    "line_number",
    "severity",
    "confidence",
    "status",
    "verification_state",
    "cwe",
    "component",
    "limitations",
    "description",
)


def short(value: uuid.UUID) -> str:
    return value.hex[:8]


def finding_excerpt(f: FindingRecord) -> ef.Excerpt:
    record: dict[str, Any] = {
        k: getattr(f, k) for k in _FINDING_FIELDS if getattr(f, k) is not None
    }
    lines = [f"{k}: {v}" for k, v in record.items()]
    return ef.Excerpt(f"finding:{short(f.id)}", "finding", "\n".join(lines), priority=9)


def result_excerpts(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    settings: Settings,
    scoped: ScopedResult,
) -> tuple[list[ef.Excerpt], list[str], list[str]]:
    """(excerpts, case messages for classification, notes about what could not be read)."""
    res = scoped.result
    notes: list[str] = []
    head = (
        f"test: {scoped.test_name}\ncheck: {scoped.check_id}\nstatus: {res.status}\n"
        f"exit_code: {res.exit_code}\nsummary: {res.summary or ''}"
    )
    items = [ef.Excerpt(f"result:{short(res.id)}", "test_case", head, priority=9)]
    messages: list[str] = []
    cases = [
        c for c in runs_repo.list_cases(db, res.id, limit=500) if c.status in ("failed", "error")
    ]
    for c in cases[:MAX_CASES]:
        body = (
            f"{c.classname or ''}::{c.name}\nstatus: {c.status}\n"
            f"message: {c.message or ''}\n{c.detail or ''}"
        )
        items.append(ef.Excerpt(f"case:{short(res.id)}_{c.ordinal}", "test_case", body, priority=8))
    messages += [f"{c.message or ''} {c.detail or ''}" for c in cases]
    logs = [e for e in runs_repo.list_result_evidence(db, res.id) if e.kind == "log"]
    for ev in logs[:MAX_LOGS]:
        try:
            _, data = runs_service.read_evidence(db, ctx, user, settings, ev.id)
        except DomainError as exc:
            notes.append(f"log {ev.filename or short(ev.id)} unavailable ({exc.code})")
            continue
        text = data.decode("utf-8", errors="replace")
        messages.append(text[:4000])
        items.append(
            ef.Excerpt(
                f"log:{short(ev.id)}_{token(ev.filename or 'log')[:30]}", "log", text, priority=5
            )
        )
    return items, messages, notes


def finding_events_excerpt(db: Session, finding: FindingRecord) -> ef.Excerpt | None:
    events = findings_repo.list_events(db, finding.id)[-8:]
    if not events:
        return None
    lines = [f"{e.event_type}: {e.from_value or ''} -> {e.to_value or ''}" for e in events]
    return ef.Excerpt(
        f"scan_summary:{short(finding.id)}", "scan_summary", "\n".join(lines), priority=4
    )
