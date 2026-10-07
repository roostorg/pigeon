from __future__ import annotations

import pytest

from pigeon.registry import Registry
from pigeon.store import Store

from .conftest import MODELSPECS_DIR


@pytest.fixture
def registry(tmp_path) -> Registry:
    return Registry(Store(tmp_path / "pigeon.db", seed_dir=MODELSPECS_DIR))


def test_list_signals_exposes_classifiers_not_byop_bases(registry: Registry):
    summaries = registry.list_signals("org-a")
    ids = {item.id for item in summaries}
    assert "shieldgemma-2b" in ids
    assert "cope-b" not in ids
    assert "shieldstral" not in ids


def test_list_signals_includes_bound_policies(registry: Registry):
    registry.store.upsert_policy("org-a", "harass", "cope-b", "Flag it.", "Harassment")
    summaries = registry.list_signals("org-a")
    custom = next(item for item in summaries if item.id == "harass")
    assert custom.kind == "byop"
    assert custom.base == "cope-b"
    assert custom.modelId == "zentropi/cope-b"


def test_resolve_unknown_version_raises(registry: Registry):
    registry.list_signals("org-a")
    with pytest.raises(KeyError, match="unknown model"):
        registry.resolve("org-a", "shieldgemma-2b@99")


def test_resolve_unversioned_uses_binding_pin(registry: Registry):
    registry.list_signals("org-a")
    resolved = registry.resolve("org-a", "shieldgemma-2b")
    assert resolved.version == "3"
    assert resolved.bound_policy is None


def test_resolve_overlays_org_endpoint(registry: Registry):
    registry.store.enable(
        "org-a", "shieldgemma-2b", "3", endpoint="https://org-a.example/infer"
    )
    resolved = registry.resolve("org-a", "shieldgemma-2b")
    assert resolved.modelspec.model.endpoint == "https://org-a.example/infer"
    other = registry.resolve("org-b", "shieldgemma-2b")
    assert other.modelspec.model.endpoint != "https://org-a.example/infer"
