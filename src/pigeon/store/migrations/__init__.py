"""Versioned SQL migration runner for PostgreSQL."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from importlib import resources
from typing import Sequence

_MIGRATION_FILE_RE = re.compile(r"^(?P<version>\d{8}_\d{6})_(?P<name>[a-z0-9_]+)\.sql$")
_ADVISORY_LOCK_KEY = "pigeon_schema_migrations"


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    sql: str


def load_postgres_migrations() -> list[Migration]:
    """Load packaged PostgreSQL migrations ordered by version."""
    package = resources.files("pigeon.store.migrations.postgres")
    found: list[Migration] = []
    seen_versions: set[str] = set()

    for entry in sorted(package.iterdir(), key=lambda p: p.name):
        if not entry.is_file() or not entry.name.endswith(".sql"):
            continue
        match = _MIGRATION_FILE_RE.match(entry.name)
        if not match:
            raise ValueError(
                f"invalid migration filename '{entry.name}'; "
                "expected YYYYMMDD_HHMMSS_description.sql"
            )
        version = match.group("version")
        if version in seen_versions:
            raise ValueError(f"duplicate migration version '{version}'")
        seen_versions.add(version)
        found.append(
            Migration(
                version=version,
                name=match.group("name"),
                sql=entry.read_text(encoding="utf-8"),
            )
        )

    found.sort(key=lambda m: m.version)
    return found


def run_postgres_migrations(
    conn,
    migrations: Sequence[Migration] | None = None,
) -> list[str]:
    """Apply pending PostgreSQL migrations in order inside a locked transaction.

    Returns the list of version strings applied during this call.
    """
    pending_source = (
        list(migrations) if migrations is not None else load_postgres_migrations()
    )
    applied_now: list[str] = []

    with conn.transaction():
        # Serialize concurrent startups (multiple workers/pods) against the same DB.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (_ADVISORY_LOCK_KEY,))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at DOUBLE PRECISION NOT NULL
            )
            """
        )
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        already_applied = {r["version"] for r in rows}

        for migration in pending_source:
            if migration.version in already_applied:
                continue
            conn.execute(migration.sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) "
                "VALUES (%s, %s, %s)",
                (migration.version, migration.name, time.time()),
            )
            applied_now.append(migration.version)

    return applied_now


def applied_postgres_migrations(conn) -> list[dict]:
    """Return applied migration records ordered by version."""
    rows = conn.execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    return [dict(r) for r in rows]
