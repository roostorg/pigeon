from __future__ import annotations

import sqlite3
import time
import json
from pathlib import Path
from typing import Optional

from .modelspecs import ModelSpec, load_modelspecs

"""Per-org state: versioned BYOP policies and which base modelspecs an org has enabled.
SQLite keeps the prototype self-contained; swap for the eng team's datastore later."""


class Store:
    def __init__(self, path: Path, seed_dir: Optional[Path] = None, seed: bool = True):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()
        if seed and seed_dir is not None and not self.modelspec_versions():
            self.seed_from_directory(seed_dir)

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS policies (
                org_id TEXT NOT NULL,
                name TEXT NOT NULL,
                version INTEGER NOT NULL,
                base TEXT NOT NULL,
                policy_text TEXT NOT NULL,
                display TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (org_id, name, version)
            );
            """
        )
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS modelspec_versions (
                name TEXT NOT NULL, version TEXT NOT NULL, spec_json TEXT NOT NULL,
                source TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY (name, version)
            );
            CREATE TABLE IF NOT EXISTS org_model_bindings (
                org_id TEXT NOT NULL, model_name TEXT NOT NULL,
                spec_version TEXT NOT NULL, endpoint TEXT, credential_ref TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (org_id, model_name)
            );
            """
        )
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(policies)")}
        if "base_version" not in columns:
            self._conn.execute("ALTER TABLE policies ADD COLUMN base_version TEXT")
        self._conn.commit()

    def latest_policies(self, org_id: str) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT p.* FROM policies p
            JOIN (
                SELECT name, MAX(version) AS v FROM policies WHERE org_id = ? GROUP BY name
            ) m ON p.name = m.name AND p.version = m.v
            WHERE p.org_id = ?
            ORDER BY p.name
            """,
            (org_id, org_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_policy(
        self, org_id: str, name: str, version: Optional[int] = None
    ) -> Optional[dict]:
        if version is None:
            row = self._conn.execute(
                "SELECT * FROM policies WHERE org_id = ? AND name = ?"
                " ORDER BY version DESC LIMIT 1",
                (org_id, name),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM policies WHERE org_id = ? AND name = ? AND version = ?",
                (org_id, name, version),
            ).fetchone()
        return dict(row) if row else None

    # ---- immutable model spec versions ----

    def seed_from_directory(self, directory: Path) -> int:
        count = 0
        for spec in load_modelspecs(directory).values():
            if self.register_modelspec(spec, source="yaml", ignore_duplicate=True):
                count += 1
        return count

    def register_modelspec(
        self, spec: ModelSpec, source: str = "api", ignore_duplicate: bool = False
    ) -> bool:
        try:
            self._conn.execute(
                "INSERT INTO modelspec_versions "
                "(name, version, spec_json, source, created_at) VALUES (?, ?, ?, ?, ?)",
                (spec.name, spec.version, spec.model_dump_json(), source, time.time()),
            )
        except sqlite3.IntegrityError:
            if not ignore_duplicate:
                raise
            return False
        self._conn.commit()
        return True

    def modelspec_versions(self, name: Optional[str] = None) -> list[dict]:
        if name is None:
            rows = self._conn.execute(
                "SELECT * FROM modelspec_versions ORDER BY name, created_at"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM modelspec_versions WHERE name = ? ORDER BY created_at",
                (name,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_modelspec(self, name: str, version: Optional[str] = None) -> Optional[ModelSpec]:
        if version is None:
            row = self._conn.execute(
                "SELECT spec_json FROM modelspec_versions WHERE name = ? "
                "ORDER BY created_at DESC LIMIT 1", (name,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT spec_json FROM modelspec_versions WHERE name = ? AND version = ?",
                (name, version),
            ).fetchone()
        return ModelSpec.model_validate(json.loads(row["spec_json"])) if row else None

    def enable(
        self, org_id: str, modelspec: str, version: Optional[str] = None,
        endpoint: Optional[str] = None, credential_ref: Optional[str] = None,
    ) -> None:
        spec = self.get_modelspec(modelspec, version)
        if spec is None:
            raise KeyError(f"unknown model spec '{modelspec}@{version}'")
        self._conn.execute(
            "INSERT INTO org_model_bindings "
            "(org_id, model_name, spec_version, endpoint, credential_ref, enabled) "
            "VALUES (?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(org_id, model_name) DO UPDATE SET spec_version=excluded.spec_version, "
            "endpoint=excluded.endpoint, credential_ref=excluded.credential_ref, enabled=1",
            (org_id, modelspec, spec.version, endpoint, credential_ref),
        )
        self._conn.commit()

    def enabled_bindings(self, org_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM org_model_bindings WHERE org_id = ? AND enabled = 1 ORDER BY model_name",
            (org_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_binding(self, org_id: str, name: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM org_model_bindings WHERE org_id = ? AND model_name = ? AND enabled = 1",
            (org_id, name),
        ).fetchone()
        return dict(row) if row else None

    def upsert_policy(
        self, org_id: str, name: str, base: str, policy_text: str, display: str
    ) -> int:
        base_spec = self.get_modelspec(base)
        if base_spec is None:
            raise KeyError(f"unknown model spec '{base}'")
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM policies WHERE org_id = ? AND name = ?",
            (org_id, name),
        ).fetchone()
        version = row["v"] + 1
        self._conn.execute(
            "INSERT INTO policies "
            "(org_id, name, version, base, base_version, policy_text, display, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (org_id, name, version, base, base_spec.version, policy_text, display, time.time()),
        )
        self._conn.commit()
        return version

    def delete_policies(self, org_id: str, name: str) -> None:
        self._conn.execute(
            "DELETE FROM policies WHERE org_id = ? AND name = ?", (org_id, name)
        )
        self._conn.commit()
