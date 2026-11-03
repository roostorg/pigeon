from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pigeon.main import create_app
from pigeon.settings import Settings

MODELSPECS_DIR = Path(__file__).resolve().parent.parent / "modelspecs"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        provider="mock",
        modelspecs_dir=MODELSPECS_DIR,
        db_path=tmp_path / "test.db",
        master_token="dev-master-token",
        token_pepper="test-pepper",
        bootstrap_tokens={"dev-token": "dev-org"},
        environment="development",
    )


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def auth() -> dict:
    return {"Authorization": "Bearer dev-token"}
