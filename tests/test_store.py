from __future__ import annotations

import sqlite3

import pytest

from pigeon.modelspecs import ModelSpec
from pigeon.store import Store

from .conftest import MODELSPECS_DIR


def test_empty_db_seeds_yaml(tmp_path):
    store = Store(tmp_path / "pigeon.db", seed_dir=MODELSPECS_DIR)
    names = {row["name"] for row in store.modelspec_versions()}
    assert names >= {"shieldgemma-2b", "shieldstral", "cope-b"}
    spec = store.get_modelspec("shieldgemma-2b", "3")
    assert spec is not None
    assert spec.kind == "classifier"


def test_populated_db_does_not_reseed_on_init(tmp_path):
    db = tmp_path / "pigeon.db"
    Store(db, seed_dir=MODELSPECS_DIR)
    store = Store(db, seed_dir=MODELSPECS_DIR)
    # Second init with seed=True still skips because versions already exist.
    count = store.seed_from_directory(MODELSPECS_DIR)
    assert count == 0
    gemma_versions = store.modelspec_versions("shieldgemma-2b")
    assert len(gemma_versions) == 1
    assert gemma_versions[0]["version"] == "3"


def test_register_modelspec_is_immutable(tmp_path):
    store = Store(tmp_path / "pigeon.db", seed=False)
    spec = ModelSpec.model_validate(
        {
            "name": "demo",
            "version": "1",
            "model": {"id": "org/demo", "runtime": "endpoint"},
            "format": "classifier",
            "labels": ["ok"],
        }
    )
    assert store.register_modelspec(spec) is True
    with pytest.raises(sqlite3.IntegrityError):
        store.register_modelspec(spec)
    assert store.register_modelspec(spec, ignore_duplicate=True) is False
    assert store.get_modelspec("demo", "missing") is None


def test_enable_pins_version_and_endpoint(tmp_path):
    store = Store(tmp_path / "pigeon.db", seed_dir=MODELSPECS_DIR)
    store.enable("org-a", "shieldgemma-2b", "3", endpoint="https://org-a.example/infer")
    binding = store.get_binding("org-a", "shieldgemma-2b")
    assert binding is not None
    assert binding["spec_version"] == "3"
    assert binding["endpoint"] == "https://org-a.example/infer"
    assert store.get_binding("org-b", "shieldgemma-2b") is None


def test_upsert_policy_pins_base_version(tmp_path):
    store = Store(tmp_path / "pigeon.db", seed_dir=MODELSPECS_DIR)
    version = store.upsert_policy("org-a", "harass", "cope-b", "Flag harassment.", "Harassment")
    assert version == 1
    policy = store.get_policy("org-a", "harass")
    assert policy is not None
    assert policy["base"] == "cope-b"
    assert policy["base_version"] == store.get_modelspec("cope-b").version


def test_delete_policies(tmp_path):
    store = Store(tmp_path / "pigeon.db", seed_dir=MODELSPECS_DIR)
    store.upsert_policy("org-a", "harass", "cope-b", "x", "x")
    store.delete_policies("org-a", "harass")
    assert store.get_policy("org-a", "harass") is None
    assert store.latest_policies("org-a") == []
