"""SQL for ``public.policies`` (global and per-project key/value rows)."""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def global_rows(db: Session) -> dict[str, Any]:
    rows = db.execute(text("SELECT key, value FROM public.policies WHERE scope = 'global'")).all()
    return {r.key: r.value for r in rows}


def project_rows(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    rows = db.execute(
        text("SELECT key, value FROM public.policies WHERE scope = 'project' AND project_id = :p"),
        {"p": project_id},
    ).all()
    return {r.key: r.value for r in rows}


def upsert_global(db: Session, key: str, value: Any, updated_by: uuid.UUID) -> None:
    db.execute(
        text(
            "INSERT INTO public.policies (scope, key, value, updated_by) "
            "VALUES ('global', :k, CAST(:v AS jsonb), :u) "
            "ON CONFLICT (key) WHERE scope = 'global' "
            "DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by"
        ),
        {"k": key, "v": json.dumps(value), "u": updated_by},
    )


def upsert_project(
    db: Session, project_id: uuid.UUID, key: str, value: Any, updated_by: uuid.UUID
) -> None:
    db.execute(
        text(
            "INSERT INTO public.policies (scope, project_id, key, value, updated_by) "
            "VALUES ('project', :p, :k, CAST(:v AS jsonb), :u) "
            "ON CONFLICT (project_id, key) WHERE scope = 'project' "
            "DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by"
        ),
        {"p": project_id, "k": key, "v": json.dumps(value), "u": updated_by},
    )
