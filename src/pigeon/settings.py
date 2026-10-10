from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DEV_TOKEN = "dev-token"
DEFAULT_DEV_ORG = "dev-org"

ENVIRONMENTS = ("development", "production")
MIN_PRODUCTION_TOKEN_LENGTH = 32
DEFAULT_MEDIA_MAX_BYTES = 10_000_000
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

    def __post_init__(self) -> None:
        if self.environment not in ENVIRONMENTS:
            raise ValueError(
                f"PIGEON_ENV must be one of {', '.join(ENVIRONMENTS)}, got '{self.environment}'"
            )
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
        )
