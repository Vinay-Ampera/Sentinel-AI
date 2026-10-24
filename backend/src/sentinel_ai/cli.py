"""Operator commands (local only; not exposed over HTTP).

    poetry run python -m sentinel_ai.cli create-super-admin --email you@example.com \
        --display-name "Your Name"

The password is read from an interactive prompt, never from arguments or files.
"""

import argparse
import getpass
import sys

from sqlalchemy import text

from sentinel_ai.core.config import ConfigError, Settings, load_settings
from sentinel_ai.db.engine import create_db_engine, create_session_factory
from sentinel_ai.services import alerts, event_retention, users
from sentinel_ai.services.artifact_store import ArtifactStore
from sentinel_ai.services.audit import RequestContext


def create_super_admin(email: str, display_name: str) -> int:
    try:
        settings = load_settings(Settings)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as db:
            try:
                user = users.bootstrap_super_admin(
                    db,
                    RequestContext(request_id="cli", ip_address=None, user_agent=None),
                    email=email,
                    display_name=display_name,
                    password=password,
                )
            except ValueError as exc:
                db.rollback()
                print(f"Not created: {exc}", file=sys.stderr)
                return 1
            db.commit()
    finally:
        engine.dispose()
    print(f"Super Admin created: {user.email} ({user.id})")
    return 0


def purge_temp(max_age_hours: float) -> int:
    try:
        settings = load_settings(Settings)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    removed = ArtifactStore(settings.artifact_root()).purge_stale_temp(max_age_hours * 3600)
    print(f"Removed {removed} stale upload temp file(s).")
    return 0


def purge_events(dry_run: bool) -> int:
    try:
        settings = load_settings(Settings)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    engine = create_db_engine(settings)
    try:
        counts = event_retention.purge(create_session_factory(engine), settings, dry_run=dry_run)
    finally:
        engine.dispose()
    verb = "Would delete" if dry_run else "Deleted"
    print(f"{verb}: " + ", ".join(f"{n} {name}" for name, n in counts.items()))
    return 0


def evaluate_alerts() -> int:
    """Run the time-driven alert rules (telemetry gap) for every project with ingestion on,
    for cron use: there is no scheduler in the application (ADR-0011, Q125)."""
    try:
        settings = load_settings(Settings)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    engine = create_db_engine(settings)
    checked = 0
    try:
        factory = create_session_factory(engine)
        with factory() as db:
            ids = [
                r.project_id
                for r in db.execute(
                    text(
                        "SELECT project_id FROM public.policies WHERE scope = 'project' "
                        "AND key = 'observability_ingest' AND (value ->> 'enabled') = 'true'"
                    )
                )
            ]
        for project_id in ids:
            with factory() as db:
                alerts.safe_time_rules(db, settings, project_id)
                db.commit()
            checked += 1
    finally:
        engine.dispose()
    print(f"Evaluated time rules for {checked} project(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel_ai.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("create-super-admin", help="Create a Super Admin account")
    cmd.add_argument("--email", required=True)
    cmd.add_argument("--display-name", required=True)
    purge = sub.add_parser("purge-temp", help="Delete abandoned upload temp files")
    purge.add_argument("--max-age-hours", type=float, default=1.0)
    events = sub.add_parser("purge-events", help="Delete expired observability data (ADR-0011)")
    events.add_argument("--dry-run", action="store_true", help="count only; delete nothing")
    sub.add_parser("evaluate-alerts", help="Run time-driven alert rules (for cron)")
    args = parser.parse_args(argv)
    if args.command == "purge-events":
        return purge_events(args.dry_run)
    if args.command == "evaluate-alerts":
        return evaluate_alerts()
    if args.command == "purge-temp":
        return purge_temp(args.max_age_hours)
    return create_super_admin(args.email, args.display_name)


if __name__ == "__main__":
    raise SystemExit(main())
