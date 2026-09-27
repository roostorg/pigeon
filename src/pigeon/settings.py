from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DEV_TOKEN = "dev-token"
DEFAULT_DEV_ORG = "dev-org"

ENVIRONMENTS = ("development", "production")
MIN_PRODUCTION_TOKEN_LENGTH = 32


@dataclass(frozen=True)
class Settings:
    provider: str
    modelspecs_dir: Path
    db_path: Path
    tokens: dict[str, str]  # bearer token -> org id
    environment: str = "production"

    def __post_init__(self) -> None:
        if self.environment not in ENVIRONMENTS:
            raise ValueError(
                f"PIGEON_ENV must be one of {', '.join(ENVIRONMENTS)}, got '{self.environment}'"
            )
        if not isinstance(self.tokens, dict) or not self.tokens:
            raise ValueError("PIGEON_TOKENS must be a non-empty JSON object of token -> org id")
        for token, org in self.tokens.items():
            if not isinstance(token, str) or not token or not isinstance(org, str) or not org:
                raise ValueError("PIGEON_TOKENS keys and values must be non-empty strings")
            if any(c.isspace() for c in token):
                raise ValueError(f"PIGEON_TOKENS: token for org '{org}' contains whitespace")
        if self.environment == "production":
            if DEFAULT_DEV_TOKEN in self.tokens:
                raise ValueError(
                    f"the default '{DEFAULT_DEV_TOKEN}' is not allowed when PIGEON_ENV=production"
                )
            for token, org in self.tokens.items():
                if len(token) < MIN_PRODUCTION_TOKEN_LENGTH:
                    raise ValueError(
                        f"PIGEON_TOKENS: token for org '{org}' is shorter than "
                        f"{MIN_PRODUCTION_TOKEN_LENGTH} characters"
                    )

    @staticmethod
    def from_env() -> "Settings":
        environment = os.environ.get("PIGEON_ENV", "production")
        raw_tokens = os.environ.get("PIGEON_TOKENS")
        if raw_tokens:
            try:
                tokens = json.loads(raw_tokens)
            except json.JSONDecodeError as exc:
                raise ValueError("PIGEON_TOKENS is not valid JSON") from exc
        elif environment == "production":
            raise ValueError("PIGEON_TOKENS must be set when PIGEON_ENV=production")
        else:
            tokens = {DEFAULT_DEV_TOKEN: DEFAULT_DEV_ORG}
        return Settings(
            provider=os.environ.get("PIGEON_PROVIDER", "mock"),
            modelspecs_dir=Path(os.environ.get("PIGEON_MODELSPECS_DIR", "modelspecs")),
            db_path=Path(os.environ.get("PIGEON_DB_PATH", "pigeon.db")),
            tokens=tokens,
            environment=environment,
        )
