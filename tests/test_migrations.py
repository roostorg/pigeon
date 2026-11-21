from __future__ import annotations

from pigeon.store.migrations import load_postgres_migrations


def test_load_postgres_migrations_returns_ordered_initial():
    migrations = load_postgres_migrations()
    assert migrations
    assert migrations[0].version == "20261121_165700"
    assert migrations[0].name == "initial"
    assert "CREATE TABLE IF NOT EXISTS orgs" in migrations[0].sql
    versions = [m.version for m in migrations]
    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
