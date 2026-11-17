from __future__ import annotations

import pytest

from pigeon.store import SqliteStore, create_store


def test_create_store_sqlite(tmp_path):
    store = create_store(backend="sqlite", db_path=tmp_path / "t.db", seed=False)
    assert isinstance(store, SqliteStore)


def test_create_store_sqlite_requires_path():
    with pytest.raises(ValueError, match="db_path"):
        create_store(backend="sqlite", seed=False)


def test_create_store_postgres_requires_url():
    with pytest.raises(ValueError, match="database_url"):
        create_store(backend="postgres", seed=False)


def test_create_store_unknown_backend():
    with pytest.raises(ValueError, match="unsupported"):
        create_store(backend="mysql", seed=False)
