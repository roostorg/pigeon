from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pigeon.main import create_app
from pigeon.settings import Settings


MODELSPECS_DIR = Path(__file__).resolve().parent.parent / "modelspecs"
MASTER_TOKEN = "test-master-token"
TOKEN_PEPPER = "test-token-pepper"


@pytest.fixture
def org_settings(tmp_path) -> Settings:
    return Settings(
        provider="mock",
        modelspecs_dir=MODELSPECS_DIR,
        db_path=tmp_path / "orgs-tokens.db",
        bootstrap_tokens={"dev-token": "dev-org"},
        environment="development",
        master_token=MASTER_TOKEN,
        token_pepper=TOKEN_PEPPER,
    )


@pytest.fixture
def org_client(org_settings) -> TestClient:
    return TestClient(create_app(org_settings))


@pytest.fixture
def master_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {MASTER_TOKEN}"}


def _create_org(client: TestClient, headers: dict[str, str], org_id: str = "acme"):
    response = client.post(
        "/v1/admin/orgs",
        headers=headers,
        json={"id": org_id, "displayName": "Acme"},
    )
    assert response.status_code in (200, 201)
    return response


def _create_token(
    client: TestClient,
    headers: dict[str, str],
    org_id: str = "acme",
    name: str = "integration-token",
):
    response = client.post(
        f"/v1/admin/orgs/{org_id}/tokens",
        headers=headers,
        json={"name": name},
    )
    assert response.status_code in (200, 201)
    body = response.json()
    assert body["name"] == name
    assert body["orgId"] == org_id
    assert isinstance(body["id"], str)
    assert isinstance(body["token"], str) and body["token"]
    return response


def test_master_creates_org_and_token_and_token_can_list_model_specs(
    org_client, master_headers
):
    _create_org(org_client, master_headers)
    token = _create_token(org_client, master_headers).json()["token"]

    modelspecs = org_client.get(
        "/v1/modelspecs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert modelspecs.status_code == 200
    assert "modelspecs" in modelspecs.json()


def test_master_can_list_orgs(org_client, master_headers):
    _create_org(org_client, master_headers, org_id="listed-org")

    response = org_client.get("/v1/admin/orgs", headers=master_headers)

    assert response.status_code == 200
    body = response.json()
    orgs = body["orgs"] if isinstance(body, dict) and "orgs" in body else body
    assert any(org["id"] == "listed-org" for org in orgs)


def test_seeded_dev_token_still_authenticates_after_app_creation(org_client):
    response = org_client.get(
        "/v1/modelspecs",
        headers={"Authorization": "Bearer dev-token"},
    )
    assert response.status_code == 200


def test_org_token_cannot_call_admin_endpoints(org_client, master_headers):
    _create_org(org_client, master_headers)
    token = _create_token(org_client, master_headers).json()["token"]
    org_headers = {"Authorization": f"Bearer {token}"}

    assert org_client.get("/v1/admin/orgs", headers=org_headers).status_code == 403
    assert (
        org_client.post(
            "/v1/admin/orgs",
            headers=org_headers,
            json={"id": "other", "displayName": "Other"},
        ).status_code
        == 403
    )


def test_master_token_cannot_call_org_routes(org_client, master_headers):
    assert org_client.get("/v1/modelspecs", headers=master_headers).status_code == 403
    assert (
        org_client.post(
            "/v1/classify",
            headers=master_headers,
            json={"model": "shieldgemma-2b", "input": {"text": "hello"}},
        ).status_code
        == 403
    )


def test_invalid_bearer_is_unauthorized_on_admin_and_org_routes(org_client):
    invalid = {"Authorization": "Bearer definitely-invalid"}

    assert org_client.get("/v1/admin/orgs").status_code == 401
    assert org_client.get("/v1/modelspecs").status_code == 401
    assert org_client.get("/v1/admin/orgs", headers=invalid).status_code == 401
    assert org_client.get("/v1/modelspecs", headers=invalid).status_code == 401


def test_duplicate_org_returns_conflict(org_client, master_headers):
    _create_org(org_client, master_headers, org_id="duplicate-org")
    duplicate = org_client.post(
        "/v1/admin/orgs",
        headers=master_headers,
        json={"id": "duplicate-org", "displayName": "Again"},
    )
    assert duplicate.status_code == 409


def test_revoked_token_can_no_longer_access_org_routes(org_client, master_headers):
    _create_org(org_client, master_headers)
    created = _create_token(org_client, master_headers).json()
    org_headers = {"Authorization": f"Bearer {created['token']}"}

    assert org_client.get("/v1/modelspecs", headers=org_headers).status_code == 200
    assert (
        org_client.post(
            "/v1/classify",
            headers=org_headers,
            json={"model": "shieldgemma-2b", "input": {"text": "hello"}},
        ).status_code
        == 200
    )

    revoked = org_client.delete(
        f"/v1/admin/orgs/acme/tokens/{created['id']}",
        headers=master_headers,
    )
    assert revoked.status_code in (200, 204)

    assert org_client.get("/v1/modelspecs", headers=org_headers).status_code == 401
    assert (
        org_client.post(
            "/v1/classify",
            headers=org_headers,
            json={"model": "shieldgemma-2b", "input": {"text": "hello"}},
        ).status_code
        == 401
    )


def test_list_tokens_never_includes_plaintext_secret_or_hash(org_client, master_headers):
    _create_org(org_client, master_headers)
    created = _create_token(org_client, master_headers).json()

    listed = org_client.get(
        "/v1/admin/orgs/acme/tokens",
        headers=master_headers,
    )
    assert listed.status_code == 200
    body = listed.json()
    tokens = body["tokens"] if isinstance(body, dict) and "tokens" in body else body
    assert any(item["id"] == created["id"] for item in tokens)
    for item in tokens:
        assert "token" not in item
        assert "secret" not in item
        assert "hash" not in item
        assert "tokenHash" not in item
        assert "token_hash" not in item
        assert created["token"] not in str(item)


def test_creating_token_for_missing_org_returns_not_found(org_client, master_headers):
    response = org_client.post(
        "/v1/admin/orgs/missing-org/tokens",
        headers=master_headers,
        json={"name": "orphan-token"},
    )
    assert response.status_code == 404
