from __future__ import annotations

import pytest

from pigeon.settings import (
    DEFAULT_DEV_TOKEN,
    DEFAULT_DEV_TOKEN_PEPPER,
    DEFAULT_MEDIA_MAX_BYTES,
    MIN_PRODUCTION_TOKEN_LENGTH,
    Settings,
)

_ENV_VARS = (
    "PIGEON_ENV",
    "PIGEON_TOKENS",
    "PIGEON_MASTER_TOKEN",
    "PIGEON_TOKEN_PEPPER",
    "PIGEON_PROVIDER",
    "PIGEON_MODELSPECS_DIR",
    "PIGEON_DB_PATH",
    "PIGEON_MEDIA_MAX_BYTES",
)

FAKE_PROD_TOKEN = "test-token-" + "x" * MIN_PRODUCTION_TOKEN_LENGTH


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_to_production_and_requires_master():
    with pytest.raises(ValueError, match="PIGEON_MASTER_TOKEN"):
        Settings.from_env()


def test_development_defaults_to_dev_token(monkeypatch):
    monkeypatch.setenv("PIGEON_ENV", "development")
    settings = Settings.from_env()
    assert settings.environment == "development"
    assert settings.bootstrap_tokens == {DEFAULT_DEV_TOKEN: "dev-org"}


def test_production_rejects_dev_token(monkeypatch):
    monkeypatch.setenv("PIGEON_MASTER_TOKEN", "x" * 32)
    monkeypatch.setenv("PIGEON_TOKEN_PEPPER", "pepper")
    monkeypatch.setenv("PIGEON_TOKENS", '{"dev-token": "dev-org"}')
    with pytest.raises(ValueError, match="not allowed"):
        Settings.from_env()


def test_production_rejects_dev_token_pepper(monkeypatch):
    monkeypatch.setenv("PIGEON_MASTER_TOKEN", "m" * 32)
    monkeypatch.setenv("PIGEON_TOKEN_PEPPER", DEFAULT_DEV_TOKEN_PEPPER)
    monkeypatch.setenv("PIGEON_TOKENS", f'{{"{FAKE_PROD_TOKEN}": "test-org"}}')
    with pytest.raises(ValueError, match="PIGEON_TOKEN_PEPPER"):
        Settings.from_env()


def test_master_token_cannot_match_bootstrap_secret(monkeypatch):
    shared = "m" * 32
    monkeypatch.setenv("PIGEON_ENV", "development")
    monkeypatch.setenv("PIGEON_MASTER_TOKEN", shared)
    monkeypatch.setenv("PIGEON_TOKENS", f'{{"{shared}": "test-org"}}')
    with pytest.raises(ValueError, match="must not match"):
        Settings.from_env()


def test_production_rejects_short_token(monkeypatch):
    monkeypatch.setenv("PIGEON_MASTER_TOKEN", "x" * 32)
    monkeypatch.setenv("PIGEON_TOKEN_PEPPER", "pepper")
    monkeypatch.setenv("PIGEON_TOKENS", '{"short-test-token": "test-org"}')
    with pytest.raises(ValueError, match="shorter than"):
        Settings.from_env()


def test_production_accepts_strong_token(monkeypatch):
    monkeypatch.setenv("PIGEON_MASTER_TOKEN", "m" * 32)
    monkeypatch.setenv("PIGEON_TOKEN_PEPPER", "pepper")
    monkeypatch.setenv("PIGEON_TOKENS", f'{{"{FAKE_PROD_TOKEN}": "test-org"}}')
    settings = Settings.from_env()
    assert settings.environment == "production"
    assert settings.bootstrap_tokens == {FAKE_PROD_TOKEN: "test-org"}


def test_development_allows_short_token(monkeypatch):
    monkeypatch.setenv("PIGEON_ENV", "development")
    monkeypatch.setenv("PIGEON_TOKENS", '{"short": "test-org"}')
    assert Settings.from_env().bootstrap_tokens == {"short": "test-org"}


def test_unknown_environment_rejected(monkeypatch):
    monkeypatch.setenv("PIGEON_ENV", "prod")
    monkeypatch.setenv("PIGEON_TOKENS", f'{{"{FAKE_PROD_TOKEN}": "test-org"}}')
    monkeypatch.setenv("PIGEON_MASTER_TOKEN", "m" * 32)
    monkeypatch.setenv("PIGEON_TOKEN_PEPPER", "pepper")
    with pytest.raises(ValueError, match="PIGEON_ENV must be one of"):
        Settings.from_env()


def test_media_max_bytes_default_and_override(monkeypatch):
    monkeypatch.setenv("PIGEON_ENV", "development")
    assert Settings.from_env().media_max_bytes == DEFAULT_MEDIA_MAX_BYTES
    monkeypatch.setenv("PIGEON_MEDIA_MAX_BYTES", "2048")
    assert Settings.from_env().media_max_bytes == 2048


def test_media_max_bytes_rejected(monkeypatch):
    monkeypatch.setenv("PIGEON_ENV", "development")
    for raw in ("0", "-1", "nope"):
        monkeypatch.setenv("PIGEON_MEDIA_MAX_BYTES", raw)
        with pytest.raises(ValueError, match="PIGEON_MEDIA_MAX_BYTES"):
            Settings.from_env()


@pytest.mark.parametrize("environment", ["development", "production"])
@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "{}",
        '{"": "org"}',
        '{"token": ""}',
        '{"token": 1}',
        f'{{" {FAKE_PROD_TOKEN}": "test-org"}}',
        f'{{"{FAKE_PROD_TOKEN} x": "test-org"}}',
    ],
)
def test_malformed_tokens_rejected(monkeypatch, environment, raw):
    monkeypatch.setenv("PIGEON_ENV", environment)
    monkeypatch.setenv("PIGEON_TOKENS", raw)
    with pytest.raises(ValueError):
        Settings.from_env()
