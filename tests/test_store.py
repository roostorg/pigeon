from __future__ import annotations

import sqlite3

import pytest

from pigeon.modelspecs import ModelSpec
from pigeon.store import Store

from .conftest import MODELSPECS_DIR

ORG = "org-a"


def test_create_org_seeds_yaml_catalog(tmp_path):
    store = Store(tmp_path / "pigeon.db", seed_dir=MODELSPECS_DIR)
    store.create_org(ORG, "Org A")
    names = {row["name"] for row in store.modelspec_versions(ORG)}
    assert names >= {"shieldgemma-2b", "shieldstral", "cope-b"}
    spec = store.get_modelspec(ORG, "shieldgemma-2b", "3")
    assert spec is not None
    assert spec.kind == "classifier"


def test_org_catalogs_are_isolated(tmp_path):
    store = Store(tmp_path / "pigeon.db", seed_dir=MODELSPECS_DIR, seed=False)
    store.create_org("org-a", "A")
    store.create_org("org-b", "B")
    private = ModelSpec.model_validate(
        {
            "name": "private-model",
            "version": "1",
            "model": {"id": "org/private", "runtime": "endpoint"},
            "format": "classifier",
            "labels": ["ok"],
        }
    )
    assert store.register_modelspec("org-a", private) is True
    assert store.get_modelspec("org-a", "private-model", "1") is not None
    assert store.get_modelspec("org-b", "private-model", "1") is None


def test_populated_org_does_not_reseed(tmp_path):
    db = tmp_path / "pigeon.db"
    store = Store(db, seed_dir=MODELSPECS_DIR)
    store.create_org(ORG, "Org A")
    count = store.seed_from_directory(MODELSPECS_DIR, ORG)
    assert count == 0
    gemma_versions = store.modelspec_versions(ORG, "shieldgemma-2b")
    assert len(gemma_versions) == 1
    assert gemma_versions[0]["version"] == "3"


def test_register_modelspec_is_immutable(tmp_path):
    store = Store(tmp_path / "pigeon.db", seed=False)
    store.create_org(ORG, "Org A")
    spec = ModelSpec.model_validate(
        {
            "name": "demo",
            "version": "1",
            "model": {"id": "org/demo", "runtime": "endpoint"},
            "format": "classifier",
            "labels": ["ok"],
        }
    )
    assert store.register_modelspec(ORG, spec) is True
    with pytest.raises(sqlite3.IntegrityError):
        store.register_modelspec(ORG, spec)
    assert store.register_modelspec(ORG, spec, ignore_duplicate=True) is False
    assert store.get_modelspec(ORG, "demo", "missing") is None


def test_enable_pins_version_and_endpoint(tmp_path):
    store = Store(tmp_path / "pigeon.db", seed_dir=MODELSPECS_DIR)
    store.create_org(ORG, "Org A")
    store.enable(ORG, "shieldgemma-2b", "3", endpoint="https://org-a.example/infer")
    binding = store.get_binding(ORG, "shieldgemma-2b")
    assert binding is not None
    assert binding["spec_version"] == "3"
    assert binding["endpoint"] == "https://org-a.example/infer"
    assert store.get_binding("org-b", "shieldgemma-2b") is None


def test_upsert_policy_pins_base_version(tmp_path):
    store = Store(tmp_path / "pigeon.db", seed_dir=MODELSPECS_DIR)
    store.create_org(ORG, "Org A")
    version = store.upsert_policy(ORG, "harass", "cope-b", "Flag harassment.", "Harassment")
    assert version == 1
    policy = store.get_policy(ORG, "harass")
    assert policy is not None
    assert policy["base"] == "cope-b"
    assert policy["base_version"] == store.get_modelspec(ORG, "cope-b").version


def test_legacy_global_catalog_stashed_until_org_exists(tmp_path):
    db = tmp_path / "legacy.db"
    demo_spec = ModelSpec.model_validate(
        {
            "name": "legacy-demo",
            "version": "1",
            "model": {"id": "org/legacy", "runtime": "endpoint"},
            "format": "classifier",
            "labels": ["ok"],
        }
    )
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE orgs (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE modelspec_versions (
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (name, version)
        );
        """
    )
    conn.execute(
        "INSERT INTO modelspec_versions (name, version, spec_json, source, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("legacy-demo", "1", demo_spec.model_dump_json(), "api", 1.0),
    )
    conn.commit()
    conn.close()

    store = Store(db, seed_dir=MODELSPECS_DIR, seed=False)
    assert store.get_modelspec("new-org", "legacy-demo", "1") is None
    store.create_org("new-org", "New Org")
    assert store.get_modelspec("new-org", "legacy-demo", "1") is not None


def test_upsert_policy_seeds_catalog_for_org_without_specs(tmp_path):
    store = Store(tmp_path / "p.db", seed_dir=MODELSPECS_DIR)
    store._conn.execute(
        "INSERT INTO orgs (id, display_name, created_at) VALUES (?, ?, ?)",
        ("orphan", "Orphan", 1.0),
    )
    store._conn.commit()
    assert store.modelspec_versions("orphan") == []
    store.upsert_policy("orphan", "pol", "cope-b", "Flag it.", "Policy")
    assert store.get_policy("orphan", "pol") is not None


def test_delete_policies(tmp_path):
    store = Store(tmp_path / "pigeon.db", seed_dir=MODELSPECS_DIR)
    store.create_org(ORG, "Org A")
    store.upsert_policy(ORG, "harass", "cope-b", "x", "x")
    store.delete_policies(ORG, "harass")
    assert store.get_policy(ORG, "harass") is None
    assert store.latest_policies(ORG) == []
