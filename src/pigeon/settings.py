from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_DEV_TOKEN = "dev-token"
DEFAULT_DEV_ORG = "dev-org"

ENVIRONMENTS = ("development", "production")
DB_BACKENDS = ("sqlite", "postgres")
MIN_PRODUCTION_TOKEN_LENGTH = 32
DEFAULT_MEDIA_MAX_BYTES = 10_000_000
DEFAULT_DB_POOL_MIN = 1
DEFAULT_DB_POOL_MAX = 10
DEFAULT_DB_POOL_TIMEOUT = 30.0
DEFAULT_DEV_MASTER_TOKEN = "dev-master-token"
DEFAULT_DEV_TOKEN_PEPPER = "dev-token-pepper"


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0 or value != value or value == float("inf"):
        raise ValueError(f"{name} must be a positive number")
    return value


@dataclass(frozen=True)
class Settings:
    provider: str
    modelspecs_dir: Path
    db_path: Path
    master_token: str
    token_pepper: str
    bootstrap_tokens: dict[str, str]
    environment: str = "production"
    seed_modelspecs: bool = False
    media_max_bytes: int = DEFAULT_MEDIA_MAX_BYTES
    db_backend: str = "sqlite"
    database_url: Optional[str] = None
    db_pool_min: int = DEFAULT_DB_POOL_MIN
    db_pool_max: int = DEFAULT_DB_POOL_MAX
    db_pool_timeout: float = DEFAULT_DB_POOL_TIMEOUT

    def __post_init__(self) -> None:
        if self.environment not in ENVIRONMENTS:
            raise ValueError(
                f"PIGEON_ENV must be one of {', '.join(ENVIRONMENTS)}, got '{self.environment}'"
            )
        if self.db_backend not in DB_BACKENDS:
            raise ValueError(
                f"PIGEON_DB_BACKEND must be one of {', '.join(DB_BACKENDS)}, "
                f"got '{self.db_backend}'"
            )
        if self.db_backend == "postgres" and not self.database_url:
            raise ValueError("PIGEON_DATABASE_URL must be set when PIGEON_DB_BACKEND=postgres")
        if self.database_url and not self.database_url.startswith(
            ("postgres://", "postgresql://")
        ):
            raise ValueError(
                "PIGEON_DATABASE_URL must start with postgres:// or postgresql://"
            )
        if self.db_pool_min < 1:
            raise ValueError("PIGEON_DB_POOL_MIN must be at least 1")
        if self.db_pool_max < self.db_pool_min:
            raise ValueError("PIGEON_DB_POOL_MAX must be >= PIGEON_DB_POOL_MIN")
        if self.db_pool_timeout <= 0:
            raise ValueError("PIGEON_DB_POOL_TIMEOUT must be positive")
        if not isinstance(self.bootstrap_tokens, dict):
            raise ValueError("PIGEON_TOKENS must be a JSON object of token -> org id")
        for token, org in self.bootstrap_tokens.items():
            if not isinstance(token, str) or not token or not isinstance(org, str) or not org:
                raise ValueError("PIGEON_TOKENS keys and values must be non-empty strings")
            if any(c.isspace() for c in token):
                raise ValueError(f"PIGEON_TOKENS: token for org '{org}' contains whitespace")
        if self.master_token in self.bootstrap_tokens:
            raise ValueError(
                "PIGEON_MASTER_TOKEN must not match any PIGEON_TOKENS bootstrap secret"
            )
        if self.environment == "production":
            if not self.master_token:
                raise ValueError("PIGEON_MASTER_TOKEN must be set in production")
            if self.master_token == DEFAULT_DEV_TOKEN:
                raise ValueError("PIGEON_MASTER_TOKEN may not be dev-token")
            if len(self.master_token) < MIN_PRODUCTION_TOKEN_LENGTH:
                raise ValueError(
                    f"PIGEON_MASTER_TOKEN must be at least {MIN_PRODUCTION_TOKEN_LENGTH} characters"
                )
            if not self.token_pepper:
                raise ValueError("PIGEON_TOKEN_PEPPER must be set in production")
            if self.token_pepper == DEFAULT_DEV_TOKEN_PEPPER:
                raise ValueError(
                    f"PIGEON_TOKEN_PEPPER may not be the default '{DEFAULT_DEV_TOKEN_PEPPER}'"
                )
            for token, org in self.bootstrap_tokens.items():
                if token == DEFAULT_DEV_TOKEN:
                    raise ValueError(
                        f"the default '{DEFAULT_DEV_TOKEN}' is not allowed when PIGEON_ENV=production"
                    )
                if len(token) < MIN_PRODUCTION_TOKEN_LENGTH:
                    raise ValueError(
                        f"PIGEON_TOKENS: token for org '{org}' is shorter than "
                        f"{MIN_PRODUCTION_TOKEN_LENGTH} characters"
                    )

    @staticmethod
    def from_env() -> "Settings":
        environment = os.environ.get("PIGEON_ENV", "production")
        raw_tokens = os.environ.get("PIGEON_TOKENS")
        tokens_file = os.environ.get("PIGEON_TOKENS_FILE")
        if raw_tokens:
            try:
                tokens = json.loads(raw_tokens)
            except json.JSONDecodeError as exc:
                raise ValueError("PIGEON_TOKENS is not valid JSON") from exc
        elif tokens_file:
            try:
                raw_file_tokens = Path(tokens_file).read_text(encoding="utf-8")
                tokens = json.loads(raw_file_tokens)
            except OSError as exc:
                raise ValueError("PIGEON_TOKENS_FILE could not be read") from exc
            except json.JSONDecodeError as exc:
                raise ValueError("PIGEON_TOKENS_FILE is not valid JSON") from exc
        else:
            tokens = {DEFAULT_DEV_TOKEN: DEFAULT_DEV_ORG} if environment == "development" else {}
        if (raw_tokens or tokens_file) and (not isinstance(tokens, dict) or not tokens):
            raise ValueError("PIGEON_TOKENS must be a non-empty JSON object of token -> org id")
        database_url = os.environ.get("PIGEON_DATABASE_URL") or None
        db_backend = os.environ.get("PIGEON_DB_BACKEND")
        if not db_backend:
            if database_url:
                # Explicit URL with a bad scheme must not silently fall back to SQLite.
                if not database_url.startswith(("postgres://", "postgresql://")):
                    raise ValueError(
                        "PIGEON_DATABASE_URL must start with postgres:// or postgresql://"
                    )
                db_backend = "postgres"
            else:
                db_backend = "sqlite"
        return Settings(
            provider=os.environ.get("PIGEON_PROVIDER", "mock"),
            modelspecs_dir=Path(os.environ.get("PIGEON_MODELSPECS_DIR", "modelspecs")),
            db_path=Path(os.environ.get("PIGEON_DB_PATH", "pigeon.db")),
            master_token=os.environ.get(
                "PIGEON_MASTER_TOKEN", DEFAULT_DEV_MASTER_TOKEN if environment == "development" else ""
            ),
            token_pepper=os.environ.get(
                "PIGEON_TOKEN_PEPPER", DEFAULT_DEV_TOKEN_PEPPER if environment == "development" else ""
            ),
            bootstrap_tokens=tokens,
            environment=environment,
            seed_modelspecs=os.environ.get("PIGEON_SEED_MODELSPECS") == "1",
            media_max_bytes=_positive_int_env(
                "PIGEON_MEDIA_MAX_BYTES",
                DEFAULT_MEDIA_MAX_BYTES,
            ),
            db_backend=db_backend,
            database_url=database_url,
            db_pool_min=_positive_int_env("PIGEON_DB_POOL_MIN", DEFAULT_DB_POOL_MIN),
            db_pool_max=_positive_int_env("PIGEON_DB_POOL_MAX", DEFAULT_DB_POOL_MAX),
            db_pool_timeout=_positive_float_env(
                "PIGEON_DB_POOL_TIMEOUT", DEFAULT_DB_POOL_TIMEOUT
            ),
        )
