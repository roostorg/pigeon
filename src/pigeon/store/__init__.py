from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from .errors import DuplicateError
from .protocol import StoreProtocol
from .sqlite import SqliteStore

# Back-compat alias used across the codebase and tests.
Store = SqliteStore

__all__ = [
    "DuplicateError",
    "PostgresStore",
    "SqliteStore",
    "Store",
    "StoreProtocol",
    "create_store",
]


def create_store(
    *,
    backend: str = "sqlite",
    db_path: Optional[Path] = None,
    database_url: Optional[str] = None,
    seed_dir: Optional[Path] = None,
    seed: bool = True,
) -> StoreProtocol:
    """Build the configured store implementation."""
    if backend == "sqlite":
        if db_path is None:
            raise ValueError("db_path is required when backend is sqlite")
        return SqliteStore(db_path, seed_dir=seed_dir, seed=seed)
    if backend == "postgres":
        if not database_url:
            raise ValueError("database_url is required when backend is postgres")
        from .postgres import PostgresStore

        return PostgresStore(database_url, seed_dir=seed_dir, seed=seed)
    raise ValueError(f"unsupported store backend '{backend}'")


def __getattr__(name: str):
    if name == "PostgresStore":
        from .postgres import PostgresStore

        return PostgresStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
