from __future__ import annotations

import os
import uuid

import pytest

from pigeon.modelspecs import ModelSpec
from pigeon.store import DuplicateError, create_store
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
