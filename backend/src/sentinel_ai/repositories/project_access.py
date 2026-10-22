"""Read-only lookups used to resolve a user's access level on a project."""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def project_exists(db: Session, project_id: uuid.UUID) -> bool:
    return (
        db.execute(text("SELECT 1 FROM public.projects WHERE id = :p"), {"p": project_id}).first()
        is not None
    )


def access_grants(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
    """Every grant the user holds on the project, as access-level words
    (``read``/``run``/``manage``). Empty when the project does not exist or the user has none.

    Sources: ownership (manage), explicit membership, team ownership of the project's team
    (manage), and team membership (the project's ``team_access``).
    """
    rows = db.execute(
        text(
            """
            SELECT 'manage' FROM public.projects p
              WHERE p.id = :p AND p.owner_user_id = :u
            UNION ALL
            SELECT m.access_level FROM public.project_memberships m
              WHERE m.project_id = :p AND m.user_id = :u
            UNION ALL
            SELECT CASE WHEN tm.team_role = 'owner' THEN 'manage' ELSE p.team_access END
              FROM public.projects p
              JOIN public.team_memberships tm ON tm.team_id = p.team_id AND tm.user_id = :u
              WHERE p.id = :p AND (tm.team_role = 'owner' OR p.team_access <> 'none')
            """
        ),
        {"p": project_id, "u": user_id},
    ).all()
    return [str(r[0]) for r in rows]
