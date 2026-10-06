from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .modelspecs import ModelSpec
from .schemas import LabelSpec, ModelSpecSummary
from .store import Store


@dataclass
class Resolved:
    modelspec: ModelSpec
    version: str
    bound_policy: Optional[str]


def _titlecase(label: str) -> str:
    return label.replace("_", " ").replace("-", " ").strip().title()


class Registry:
    """Turns DB-backed modelspecs + per-org policies into the signal list a consumer sees,
    and resolves a model reference ("name" or "name@version") to something callable."""

    def __init__(self, store: Store):
        self.store = store

    def ensure_defaults(self, org_id: str) -> None:
        """Convenience seed: bind every spec only when the org has no bindings."""
        if not self.store.enabled_bindings(org_id):
            for row in self.store.modelspec_versions():
                self.store.enable(org_id, row["name"], row["version"])

    def list_signals(self, org_id: str) -> list[ModelSpecSummary]:
        self.ensure_defaults(org_id)
        summaries: list[ModelSpecSummary] = []

        # Fixed-label classifiers are exposed directly. BYOP bases are exposed only through
        # bound policies (below); completion models are Osprey-only and not signals.
        for binding in self.store.enabled_bindings(org_id):
            name = binding["model_name"]
            mf = self.store.get_modelspec(name, binding["spec_version"])
            if mf is not None and mf.kind == "classifier":
                summaries.append(self._classifier_summary(mf))

        for pol in self.store.latest_policies(org_id):
            base = self.store.get_modelspec(pol["base"], pol.get("base_version"))
            if base is None:
                continue
            binding = self.store.get_binding(org_id, pol["base"])
            if binding and binding.get("endpoint"):
                base = base.model_copy(deep=True)
                base.model.endpoint = binding["endpoint"]
            summaries.append(
                ModelSpecSummary(
                    id=pol["name"],
                    version=str(pol["version"]),
                    kind="byop",
                    base=pol["base"],
                    modelId=base.model.id,
                    inputTypes=list(base.input_types),
                    labels=[LabelSpec(id="verdict", display=pol["display"])],
                )
            )
        return summaries

    def _classifier_summary(self, mf: ModelSpec) -> ModelSpecSummary:
        labels = [LabelSpec(id=lbl, display=_titlecase(lbl)) for lbl in mf.labels]
        return ModelSpecSummary(
            id=mf.name,
            version=mf.version,
            kind="classifier",
            modelId=mf.model.id,
            inputTypes=list(mf.input_types),
            labels=labels,
        )

    def resolve(self, org_id: str, model_ref: str) -> Resolved:
        name, _, version = model_ref.partition("@")

        pol = self.store.get_policy(org_id, name, int(version) if version.isdigit() else None)
        if pol is not None:
            base = self.store.get_modelspec(pol["base"], pol.get("base_version"))
            if base is None:
                raise KeyError(
                    f"base model spec '{pol['base']}' not found for policy '{name}'"
                )
            binding = self.store.get_binding(org_id, pol["base"])
            if binding and binding.get("endpoint"):
                base = base.model_copy(deep=True)
                base.model.endpoint = binding["endpoint"]
            return Resolved(
                modelspec=base, version=str(pol["version"]), bound_policy=pol["policy_text"]
            )

        binding = self.store.get_binding(org_id, name)
        mf = self.store.get_modelspec(name, version or (binding or {}).get("spec_version"))
        if mf is None:
            raise KeyError(f"unknown model '{name}'")
        if version and mf.version != version:
            raise KeyError(f"unknown model '{model_ref}'")
        if binding and binding.get("endpoint"):
            mf = mf.model_copy(deep=True)
            mf.model.endpoint = binding["endpoint"]
        return Resolved(modelspec=mf, version=mf.version, bound_policy=None)
