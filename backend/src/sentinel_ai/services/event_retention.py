"""Retention for observability data (ADR-0011, decision 11; Q124).

Samples and hourly buckets expire first, then resolved alerts and quiet groups; open alerts,
alerts and groups a regression proposal points to, and audit rows are kept. There is no
scheduler (Q70), so ``cli purge-events`` runs this (with ``--dry-run`` to count only) and an
operator or cron runs it; read paths also ignore expired samples."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from sentinel_ai.core.config import Settings
from sentinel_ai.repositories import observability as repo

KEY_RETENTION_DAYS = 365
STATS_RETENTION_DAYS = 35


def purge(
    session_factory: sessionmaker[Session], settings: Settings, *, dry_run: bool,
    now: datetime | None = None,
) -> dict[str, int]:  # fmt: skip
    now = now or datetime.now(UTC)
    with session_factory() as db:
        counts = repo.purge(
            db,
            sample_before=now - timedelta(days=settings.event_sample_retention_days),
            group_before=now - timedelta(days=settings.event_group_retention_days),
            key_before=now - timedelta(days=KEY_RETENTION_DAYS),
            stats_before=(now - timedelta(days=STATS_RETENTION_DAYS)).date(),
            dry_run=dry_run,
        )
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return counts
