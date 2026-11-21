from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from pigeon.modelspecs import ModelSpec
from pigeon.store import DuplicateError, create_store
from pigeon.store.migrations import Migration, run_postgres_migrations
from pigeon.tokens import hash_token

from .conftest import MODELSPECS_DIR

pytest.importorskip("psycopg")

DATABASE_URL = os.environ.get("PIGEON_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PIGEON_TEST_DATABASE_URL to run Postgres store tests",
)


@pytest.fixture
def store():
    assert DATABASE_URL is not None
    s = create_store(
        backend="postgres",
        database_url=DATABASE_URL,
        seed_dir=MODELSPECS_DIR,
        seed=True,
    )
    yield s
    s.close()


def test_postgres_create_org_seeds_catalog(store):
    org_id = f"pg-{uuid.uuid4().hex[:8]}"
    store.create_org(org_id, "PG Org")
    names = {row["name"] for row in store.modelspec_versions(org_id)}
    assert "shieldgemma-2b" in names
    assert store.get_modelspec(org_id, "shieldgemma-2b", "3") is not None


def test_postgres_register_duplicate(store):
    org_id = f"pg-{uuid.uuid4().hex[:8]}"
    store.create_org(org_id, "PG Org")
    spec = ModelSpec.model_validate(
        {
            "name": "demo",
            "version": "1",
            "model": {"id": "org/demo", "runtime": "endpoint"},
            "format": "classifier",
            "labels": ["ok"],
        }
    )
    assert store.register_modelspec(org_id, spec) is True
    with pytest.raises(DuplicateError):
        store.register_modelspec(org_id, spec)


def test_postgres_duplicate_org_then_list_still_works(store):
    """UniqueViolation must roll back so the shared connection stays usable."""
    org_id = f"pg-{uuid.uuid4().hex[:8]}"
    store.create_org(org_id, "PG Org")
    with pytest.raises(DuplicateError):
        store.create_org(org_id, "Again")
    ids = {row["id"] for row in store.list_orgs()}
    assert org_id in ids


def test_postgres_org_isolation(store):
    a = f"pg-a-{uuid.uuid4().hex[:8]}"
    b = f"pg-b-{uuid.uuid4().hex[:8]}"
    store.create_org(a, "A")
    store.create_org(b, "B")
    private = ModelSpec.model_validate(
        {
            "name": "only-a",
            "version": "1",
            "model": {"id": "org/a", "runtime": "endpoint"},
            "format": "classifier",
            "labels": ["ok"],
        }
    )
    store.register_modelspec(a, private)
    assert store.get_modelspec(a, "only-a", "1") is not None
    assert store.get_modelspec(b, "only-a", "1") is None


def test_postgres_token_create_resolve_revoke(store):
    org_id = f"pg-{uuid.uuid4().hex[:8]}"
    store.create_org(org_id, "PG Org")
    token_hash = hash_token(f"secret-{uuid.uuid4().hex}", "pepper")
    row = store.create_api_token(org_id, "ci", token_hash)
    assert store.resolve_api_token(token_hash)["id"] == row["id"]
    assert store.revoke_api_token(org_id, row["id"]) is True
    assert store.resolve_api_token(token_hash) is None


def test_postgres_policy_versions_enable_and_delete(store):
    org_id = f"pg-{uuid.uuid4().hex[:8]}"
    store.create_org(org_id, "PG Org")
    v1 = store.upsert_policy(org_id, "harass", "cope-b", "Flag it.", "Harassment")
    v2 = store.upsert_policy(org_id, "harass", "cope-b", "Flag louder.", "Harassment")
    assert v1 == 1
    assert v2 == 2
    latest = store.get_policy(org_id, "harass")
    assert latest is not None
    assert latest["version"] == 2
    store.enable(org_id, "cope-b", "1", endpoint="https://example.test/infer")
    binding = store.get_binding(org_id, "cope-b")
    assert binding is not None
    assert binding["endpoint"] == "https://example.test/infer"
    store.delete_policies(org_id, "harass")
    assert store.get_policy(org_id, "harass") is None


def test_postgres_seed_is_idempotent(store):
    org_id = f"pg-{uuid.uuid4().hex[:8]}"
    store.create_org(org_id, "PG Org")
    first = store.seed_from_directory(MODELSPECS_DIR, org_id)
    second = store.seed_from_directory(MODELSPECS_DIR, org_id)
    assert first == 0  # already seeded by create_org
    assert second == 0


def test_postgres_migrations_recorded_and_idempotent(store):
    applied = store.applied_migrations()
    versions = [row["version"] for row in applied]
    assert "20261121_165700" in versions
    with store._pool.connection() as conn:
        assert run_postgres_migrations(conn) == []


def test_postgres_migration_runner_applies_incremental_in_isolated_schema(store):
    from psycopg import sql

    schema = f"test_mig_{uuid.uuid4().hex[:8]}"
    with store._pool.connection() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            first = run_postgres_migrations(conn)
            assert first == ["20261121_165700"]
            assert run_postgres_migrations(conn) == []
            extra = Migration(
                version="20261121_170000",
                name="test_extra_col",
                sql="ALTER TABLE orgs ADD COLUMN notes TEXT;",
            )
            second = run_postgres_migrations(conn, migrations=[extra])
            assert second == ["20261121_170000"]
            assert run_postgres_migrations(conn, migrations=[extra]) == []
        finally:
            conn.execute("SET search_path TO public")
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


def test_postgres_concurrent_policy_upsert_across_pool(store):
    org_id = f"pg-{uuid.uuid4().hex[:8]}"
    store.create_org(org_id, "PG Org")

    def write(i: int) -> int:
        return store.upsert_policy(
            org_id, "concurrent-pol", "cope-b", f"Rule {i}", "Concurrent"
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        versions = list(pool.map(write, range(6)))

    assert sorted(versions) == [1, 2, 3, 4, 5, 6]
    latest = store.get_policy(org_id, "concurrent-pol")
    assert latest is not None
    assert latest["version"] == 6
