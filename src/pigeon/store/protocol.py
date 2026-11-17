from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

from ..modelspecs import ModelSpec


class StoreProtocol(Protocol):
    """Persistence seam used by registry, auth, and the HTTP API."""

    def close(self) -> None: ...

    def create_org(self, org_id: str, display_name: str) -> dict: ...

    def list_orgs(self) -> list[dict]: ...

    def get_org(self, org_id: str) -> Optional[dict]: ...

    def create_api_token(self, org_id: str, name: str, token_hash: str) -> dict: ...

    def list_api_tokens(self, org_id: Optional[str] = None) -> list[dict]: ...

    def revoke_api_token(self, org_id: str, token_id: str) -> bool: ...

    def resolve_api_token(self, token_hash: str) -> Optional[dict]: ...

    def seed_tokens_from_map(self, tokens: dict[str, str], pepper: str = "") -> int: ...

    def latest_policies(self, org_id: str) -> list[dict]: ...

    def get_policy(
        self, org_id: str, name: str, version: Optional[int] = None
    ) -> Optional[dict]: ...

    def ensure_org_catalog(self, org_id: str) -> None: ...

    def seed_from_directory(self, directory: Path, org_id: str) -> int: ...

    def register_modelspec(
        self,
        org_id: str,
        spec: ModelSpec,
        source: str = "api",
        ignore_duplicate: bool = False,
    ) -> bool: ...

    def modelspec_versions(
        self, org_id: str, name: Optional[str] = None
    ) -> list[dict]: ...

    def get_modelspec(
        self, org_id: str, name: str, version: Optional[str] = None
    ) -> Optional[ModelSpec]: ...

    def enable(
        self,
        org_id: str,
        modelspec: str,
        version: Optional[str] = None,
        endpoint: Optional[str] = None,
        credential_ref: Optional[str] = None,
    ) -> None: ...

    def enabled_bindings(self, org_id: str) -> list[dict]: ...

    def get_binding(self, org_id: str, name: str) -> Optional[dict]: ...

    def upsert_policy(
        self, org_id: str, name: str, base: str, policy_text: str, display: str
    ) -> int: ...

    def delete_policies(self, org_id: str, name: str) -> None: ...
