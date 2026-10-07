from __future__ import annotations

import pytest

from pigeon.settings import DEFAULT_DEV_TOKEN, MIN_PRODUCTION_TOKEN_LENGTH, Settings

_ENV_VARS = (
    "PIGEON_ENV",
    "PIGEON_TOKENS",
    "PIGEON_PROVIDER",
    "PIGEON_MODELSPECS_DIR",
    "PIGEON_DB_PATH",
)

FAKE_PROD_TOKEN = "test-token-" + "x" * MIN_PRODUCTION_TOKEN_LENGTH


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_to_production_and_requires_tokens():
    with pytest.raises(ValueError, match="PIGEON_TOKENS must be set"):
        Settings.from_env()


def test_development_defaults_to_dev_token(monkeypatch):
    monkeypatch.setenv("PIGEON_ENV", "development")
    settings = Settings.from_env()
    assert settings.environment == "development"
    assert settings.tokens == {DEFAULT_DEV_TOKEN: "dev-org"}


def test_production_rejects_dev_token(monkeypatch):
    monkeypatch.setenv("PIGEON_TOKENS", '{"dev-token": "dev-org"}')
    with pytest.raises(ValueError, match="not allowed"):
        Settings.from_env()


def test_production_rejects_short_token(monkeypatch):
    monkeypatch.setenv("PIGEON_TOKENS", '{"short-test-token": "test-org"}')
    with pytest.raises(ValueError, match="shorter than"):
        Settings.from_env()


def test_production_accepts_strong_token(monkeypatch):
    monkeypatch.setenv("PIGEON_TOKENS", f'{{"{FAKE_PROD_TOKEN}": "test-org"}}')
    settings = Settings.from_env()
    assert settings.environment == "production"
    assert settings.tokens == {FAKE_PROD_TOKEN: "test-org"}


def test_development_allows_short_token(monkeypatch):
    monkeypatch.setenv("PIGEON_ENV", "development")
    monkeypatch.setenv("PIGEON_TOKENS", '{"short": "test-org"}')
    assert Settings.from_env().tokens == {"short": "test-org"}


def test_unknown_environment_rejected(monkeypatch):
    monkeypatch.setenv("PIGEON_ENV", "prod")
    monkeypatch.setenv("PIGEON_TOKENS", f'{{"{FAKE_PROD_TOKEN}": "test-org"}}')
    with pytest.raises(ValueError, match="PIGEON_ENV must be one of"):
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
