from __future__ import annotations

import sqlite3
import secrets
from typing import Awaitable, Callable

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from .classify import classify
from .auth import AuthContext, require_master, require_org
from .providers.base import ProviderClient
from .registry import Registry
from .schemas import (
    ClassifyRequest,
    ClassifyResponse,
    ModelSpecsResponse,
    PolicyCreate,
    PolicyResponse,
    ModelSpecCreate,
    ModelSpecEnable,
    ModelSpecImport,
)
from .tokens import hash_token

GetAuth = Callable[..., Awaitable[AuthContext]]


def build_router(
    registry: Registry, provider: ProviderClient, get_auth: GetAuth, token_pepper: str
) -> APIRouter:
    router = APIRouter()

    async def get_org(auth: AuthContext = Depends(get_auth)) -> str:
        return require_org(auth)

    async def get_master(auth: AuthContext = Depends(get_auth)) -> None:
        require_master(auth)

    @router.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @router.get("/v1/modelspecs", response_model=ModelSpecsResponse)
    async def list_modelspecs(org: str = Depends(get_org)) -> ModelSpecsResponse:
        return ModelSpecsResponse(modelspecs=registry.list_signals(org))

    @router.post("/v1/modelspecs", response_model=ModelSpecCreate, status_code=201)
    async def register_modelspec(
        body: ModelSpecCreate, org: str = Depends(get_org)
    ) -> ModelSpecCreate:
        del org  # auth required; catalog is still global in this prototype
        try:
            registry.store.register_modelspec(body)
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="model spec version already exists")
        return body

    @router.post("/v1/modelspecs/{name}/enable")
    async def enable_modelspec(
        name: str, body: ModelSpecEnable, org: str = Depends(get_org)
    ) -> dict:
        try:
            registry.store.enable(
                org, name, body.version, body.endpoint, body.credential_ref
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"name": name, "version": body.version, "enabled": True}

    @router.post("/v1/modelspecs/import")
    async def import_modelspecs(
        body: ModelSpecImport, org: str = Depends(get_org)
    ) -> dict:
        del org  # auth required; catalog is still global in this prototype
        try:
            raw = yaml.safe_load(body.text)
            values = raw if isinstance(raw, list) else [raw]
            specs = [ModelSpecCreate.model_validate(value) for value in values]
        except (yaml.YAMLError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"invalid model spec: {exc}")
        if body.dry_run:
            return {"count": len(specs), "dry_run": True}
        for spec in specs:
            try:
                registry.store.register_modelspec(spec, source="import")
            except sqlite3.IntegrityError:
                raise HTTPException(status_code=409, detail=f"{spec.name}@{spec.version} exists")
        return {"count": len(specs), "dry_run": False}

    @router.get("/v1/modelspecs/{name}/export", response_class=PlainTextResponse)
    async def export_modelspec(name: str, org: str = Depends(get_org), version: str | None = None):
        binding = registry.store.get_binding(org, name)
        selected = version or (binding or {}).get("spec_version")
        spec = registry.store.get_modelspec(name, selected)
        if spec is None:
            raise HTTPException(status_code=404, detail="model spec version not found")
        return yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False)

    @router.post("/v1/classify", response_model=ClassifyResponse)
    async def classify_endpoint(
        req: ClassifyRequest, org: str = Depends(get_org)
    ) -> ClassifyResponse:
        try:
            version, results = await classify(
                org_id=org,
                model_ref=req.model,
                text=req.input.text,
                media_url=req.input.mediaUrl,
                policy=req.policy,
                registry=registry,
                provider=provider,
                context=req.input.context,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        name = req.model.split("@", 1)[0]
        return ClassifyResponse(model=f"{name}@{version}", results=results)

    @router.get("/v1/policies")
    async def list_policies(org: str = Depends(get_org)) -> dict:
        policies = [
            {
                "id": p["name"],
                "version": str(p["version"]),
                "base": p["base"],
                "display": p["display"],
            }
            for p in registry.store.latest_policies(org)
        ]
        return {"policies": policies}

    @router.post("/v1/policies", response_model=PolicyResponse)
    async def create_policy(
        body: PolicyCreate, org: str = Depends(get_org)
    ) -> PolicyResponse:
        base = registry.store.get_modelspec(body.base)
        if base is None or not base.policy_argument:
            raise HTTPException(
                status_code=422,
                detail=f"base '{body.base}' is not a policy-steerable (BYOP) model spec",
            )
        display = body.display or body.name
        version = registry.store.upsert_policy(
            org, body.name, body.base, body.policyText, display
        )
        return PolicyResponse(
            id=body.name, version=str(version), base=body.base, display=display
        )

    @router.delete("/v1/policies/{name}", status_code=204)
    async def delete_policy(name: str, org: str = Depends(get_org)) -> None:
        if registry.store.get_policy(org, name) is None:
            raise HTTPException(status_code=404, detail="policy not found")
        registry.store.delete_policies(org, name)

    @router.post("/v1/admin/orgs", status_code=201)
    async def create_org(body: dict, _: None = Depends(get_master)) -> dict:
        org_id = body.get("id")
        display_name = body.get("displayName")
        if not isinstance(org_id, str) or not org_id or not isinstance(display_name, str) or not display_name:
            raise HTTPException(status_code=422, detail="id and displayName are required")
        try:
            row = registry.store.create_org(org_id, display_name)
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="organization already exists")
        return {"id": row["id"], "displayName": row["display_name"], "createdAt": row["created_at"]}

    @router.get("/v1/admin/orgs")
    async def list_orgs(_: None = Depends(get_master)) -> dict:
        return {
            "orgs": [
                {"id": row["id"], "displayName": row["display_name"], "createdAt": row["created_at"]}
                for row in registry.store.list_orgs()
            ]
        }

    @router.post("/v1/admin/orgs/{org_id}/tokens", status_code=201)
    async def create_token(org_id: str, body: dict, _: None = Depends(get_master)) -> dict:
        if registry.store.get_org(org_id) is None:
            raise HTTPException(status_code=404, detail="organization not found")
        name = body.get("name")
        if not isinstance(name, str) or not name:
            raise HTTPException(status_code=422, detail="name is required")
        secret = secrets.token_urlsafe(32)
        try:
            row = registry.store.create_api_token(org_id, name, hash_token(secret, token_pepper))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="token could not be created")
        return {"id": row["id"], "name": row["name"], "orgId": org_id, "token": secret}

    @router.get("/v1/admin/orgs/{org_id}/tokens")
    async def list_tokens(org_id: str, _: None = Depends(get_master)) -> dict:
        if registry.store.get_org(org_id) is None:
            raise HTTPException(status_code=404, detail="organization not found")
        return {
            "tokens": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "createdAt": row["created_at"],
                    "revokedAt": row["revoked_at"],
                }
                for row in registry.store.list_api_tokens(org_id)
            ]
        }

    @router.delete("/v1/admin/orgs/{org_id}/tokens/{token_id}", status_code=204)
    async def revoke_token(org_id: str, token_id: str, _: None = Depends(get_master)) -> None:
        if not registry.store.revoke_api_token(org_id, token_id):
            raise HTTPException(status_code=404, detail="token not found")

    return router
