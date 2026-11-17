from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from ..modelspecs import ModelSpec, load_modelspecs
from .errors import DuplicateError

"""PostgreSQL implementation of the store protocol (psycopg3)."""

_POLICY_VERSION_RETRIES = 8


class PostgresStore:
    def __init__(
        self,
        database_url: str,
        seed_dir: Optional[Path] = None,
        seed: bool = True,
    ):
        self._database_url = database_url
        self._seed_dir = seed_dir
        self._seed = seed
        self._lock = threading.Lock()
        # Autocommit for standalone statements so reads do not leave idle
        # transactions open. Multi-statement writes use _transaction().
        self._conn = self._connect()
        self._init()

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            self._database_url, row_factory=dict_row, autocommit=True
        )

    def _ensure_conn(self) -> None:
        """Reconnect if the socket was closed (DB restart, idle proxy drop)."""
        if self._conn.closed:
            self._conn = self._connect()

    def _recover_conn(self) -> None:
        try:
            if not self._conn.closed:
                self._conn.close()
        except Exception:
            pass
        self._conn = self._connect()

    def close(self) -> None:
        with self._lock:
            if not self._conn.closed:
                self._conn.close()

    @contextmanager
    def _transaction(self) -> Iterator:
        """Hold the lock for a full write transaction (commit or rollback)."""
        import psycopg

        with self._lock:
            try:
                self._ensure_conn()
            except psycopg.OperationalError:
                self._recover_conn()
            previous = True
            try:
                previous = self._conn.autocommit
                self._conn.autocommit = False
                yield self._conn
                self._conn.commit()
            except psycopg.OperationalError:
                try:
                    if not self._conn.closed:
                        self._conn.rollback()
                except Exception:
                    pass
                self._recover_conn()
                raise
            except Exception:
                try:
                    if not self._conn.closed:
                        self._conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                # Never let cleanup mask the original error (e.g. dead socket).
                try:
                    if not self._conn.closed:
                        self._conn.autocommit = previous
                except Exception:
                    pass

    def _fetchall(self, sql: str, params: tuple | list = ()) -> list[dict]:
        import psycopg

        with self._lock:
            try:
                self._ensure_conn()
                rows = self._conn.execute(sql, params).fetchall()
            except psycopg.OperationalError:
                self._recover_conn()
                rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def _fetchone(self, sql: str, params: tuple | list = ()) -> Optional[dict]:
        import psycopg

        with self._lock:
            try:
                self._ensure_conn()
                row = self._conn.execute(sql, params).fetchone()
            except psycopg.OperationalError:
                self._recover_conn()
                row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _init(self) -> None:
        with self._transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orgs (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_tokens (
                    id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL REFERENCES orgs(id),
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at DOUBLE PRECISION NOT NULL,
                    revoked_at DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS policies (
                    org_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    base TEXT NOT NULL,
                    base_version TEXT,
                    policy_text TEXT NOT NULL,
                    display TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (org_id, name, version)
                );
                CREATE TABLE IF NOT EXISTS modelspec_versions (
                    org_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (org_id, name, version)
                );
                CREATE TABLE IF NOT EXISTS org_model_bindings (
                    org_id TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    spec_version TEXT NOT NULL,
                    endpoint TEXT,
                    credential_ref TEXT,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    PRIMARY KEY (org_id, model_name)
                );
                """
            )
            # Greenfield CREATE IF NOT EXISTS does not add columns to older DBs.
            # Check the catalog first: ALTER still takes an AccessExclusiveLock
            # even with IF NOT EXISTS, which can block behind a live app connection.
            has_base_version = conn.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'policies'
                  AND column_name = 'base_version'
                """
            ).fetchone()
            if has_base_version is None:
                conn.execute("SET LOCAL lock_timeout = '5s'")
                conn.execute("ALTER TABLE policies ADD COLUMN base_version TEXT")

    def create_org(self, org_id: str, display_name: str) -> dict:
        import psycopg.errors

        row = {"id": org_id, "display_name": display_name, "created_at": time.time()}
        try:
            with self._transaction() as conn:
                conn.execute(
                    "INSERT INTO orgs (id, display_name, created_at) VALUES (%s, %s, %s)",
                    (row["id"], row["display_name"], row["created_at"]),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateError(f"organization '{org_id}' already exists") from exc
        self.ensure_org_catalog(org_id)
        return row

    def list_orgs(self) -> list[dict]:
        return self._fetchall("SELECT * FROM orgs ORDER BY id")

    def get_org(self, org_id: str) -> Optional[dict]:
        return self._fetchone("SELECT * FROM orgs WHERE id = %s", (org_id,))

    def create_api_token(self, org_id: str, name: str, token_hash: str) -> dict:
        import psycopg.errors

        row = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "name": name,
            "token_hash": token_hash,
            "created_at": time.time(),
            "revoked_at": None,
        }
        try:
            with self._transaction() as conn:
                conn.execute(
                    "INSERT INTO api_tokens "
                    "(id, org_id, name, token_hash, created_at, revoked_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        row["id"],
                        row["org_id"],
                        row["name"],
                        row["token_hash"],
                        row["created_at"],
                        row["revoked_at"],
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateError("token could not be created") from exc
        return row

    def list_api_tokens(self, org_id: Optional[str] = None) -> list[dict]:
        if org_id is None:
            return self._fetchall(
                "SELECT id, org_id, name, created_at, revoked_at FROM api_tokens "
                "ORDER BY created_at, id"
            )
        return self._fetchall(
            "SELECT id, org_id, name, created_at, revoked_at FROM api_tokens "
            "WHERE org_id = %s ORDER BY created_at, id",
            (org_id,),
        )

    def revoke_api_token(self, org_id: str, token_id: str) -> bool:
        with self._transaction() as conn:
            cursor = conn.execute(
                "UPDATE api_tokens SET revoked_at = %s "
                "WHERE id = %s AND org_id = %s AND revoked_at IS NULL",
                (time.time(), token_id, org_id),
            )
            return cursor.rowcount > 0

    def resolve_api_token(self, token_hash: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM api_tokens WHERE token_hash = %s AND revoked_at IS NULL",
            (token_hash,),
        )

    def seed_tokens_from_map(self, tokens: dict[str, str], pepper: str = "") -> int:
        from ..tokens import hash_token

        count = 0
        for secret, org_id in tokens.items():
            if self.get_org(org_id) is None:
                self.create_org(org_id, org_id)
            else:
                self.ensure_org_catalog(org_id)
            token_hash = hash_token(secret, pepper)
            if self._fetchone(
                "SELECT 1 AS ok FROM api_tokens WHERE token_hash = %s", (token_hash,)
            ):
                continue
            self.create_api_token(org_id, "bootstrap", token_hash)
            count += 1
        return count

    def latest_policies(self, org_id: str) -> list[dict]:
        return self._fetchall(
            """
            SELECT p.* FROM policies p
            JOIN (
                SELECT name, MAX(version) AS v FROM policies
                WHERE org_id = %s GROUP BY name
            ) m ON p.name = m.name AND p.version = m.v
            WHERE p.org_id = %s
            ORDER BY p.name
            """,
            (org_id, org_id),
        )

    def get_policy(
        self, org_id: str, name: str, version: Optional[int] = None
    ) -> Optional[dict]:
        if version is None:
            return self._fetchone(
                "SELECT * FROM policies WHERE org_id = %s AND name = %s"
                " ORDER BY version DESC LIMIT 1",
                (org_id, name),
            )
        return self._fetchone(
            "SELECT * FROM policies WHERE org_id = %s AND name = %s AND version = %s",
            (org_id, name, version),
        )

    def ensure_org_catalog(self, org_id: str) -> None:
        if self.modelspec_versions(org_id):
            return
        if not self._seed or self._seed_dir is None:
            return
        self.seed_from_directory(self._seed_dir, org_id)

    def seed_from_directory(self, directory: Path, org_id: str) -> int:
        count = 0
        for spec in load_modelspecs(directory).values():
            if self.register_modelspec(
                org_id, spec, source="yaml", ignore_duplicate=True
            ):
                count += 1
        return count

    def register_modelspec(
        self,
        org_id: str,
        spec: ModelSpec,
        source: str = "api",
        ignore_duplicate: bool = False,
    ) -> bool:
        import psycopg.errors

        params = (
            org_id,
            spec.name,
            spec.version,
            spec.model_dump_json(),
            source,
            time.time(),
        )
        if ignore_duplicate:
            # ON CONFLICT avoids a unique_violation ERROR in the Postgres log
            # when YAML seed / ensure_org_catalog re-touches existing rows.
            with self._transaction() as conn:
                cursor = conn.execute(
                    "INSERT INTO modelspec_versions "
                    "(org_id, name, version, spec_json, source, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (org_id, name, version) DO NOTHING",
                    params,
                )
                return cursor.rowcount > 0
        try:
            with self._transaction() as conn:
                conn.execute(
                    "INSERT INTO modelspec_versions "
                    "(org_id, name, version, spec_json, source, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    params,
                )
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateError(
                f"model spec '{spec.name}@{spec.version}' already exists"
            ) from exc
        return True

    def modelspec_versions(
        self, org_id: str, name: Optional[str] = None
    ) -> list[dict]:
        if name is None:
            return self._fetchall(
                "SELECT * FROM modelspec_versions WHERE org_id = %s "
                "ORDER BY name, created_at",
                (org_id,),
            )
        return self._fetchall(
            "SELECT * FROM modelspec_versions WHERE org_id = %s AND name = %s "
            "ORDER BY created_at",
            (org_id, name),
        )

    def get_modelspec(
        self, org_id: str, name: str, version: Optional[str] = None
    ) -> Optional[ModelSpec]:
        if version is None:
            row = self._fetchone(
                "SELECT spec_json FROM modelspec_versions "
                "WHERE org_id = %s AND name = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (org_id, name),
            )
        else:
            row = self._fetchone(
                "SELECT spec_json FROM modelspec_versions "
                "WHERE org_id = %s AND name = %s AND version = %s",
                (org_id, name, version),
            )
        if row is None:
            return None
        return ModelSpec.model_validate(json.loads(row["spec_json"]))

    def enable(
        self,
        org_id: str,
        modelspec: str,
        version: Optional[str] = None,
        endpoint: Optional[str] = None,
        credential_ref: Optional[str] = None,
    ) -> None:
        self.ensure_org_catalog(org_id)
        spec = self.get_modelspec(org_id, modelspec, version)
        if spec is None:
            raise KeyError(f"unknown model spec '{modelspec}@{version}'")
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO org_model_bindings "
                "(org_id, model_name, spec_version, endpoint, credential_ref, enabled) "
                "VALUES (%s, %s, %s, %s, %s, TRUE) "
                "ON CONFLICT (org_id, model_name) DO UPDATE SET "
                "spec_version = EXCLUDED.spec_version, "
                "endpoint = EXCLUDED.endpoint, "
                "credential_ref = EXCLUDED.credential_ref, "
                "enabled = TRUE",
                (org_id, modelspec, spec.version, endpoint, credential_ref),
            )

    def enabled_bindings(self, org_id: str) -> list[dict]:
        return self._fetchall(
            "SELECT * FROM org_model_bindings "
            "WHERE org_id = %s AND enabled = TRUE ORDER BY model_name",
            (org_id,),
        )

    def get_binding(self, org_id: str, name: str) -> Optional[dict]:
        return self._fetchone(
            "SELECT * FROM org_model_bindings "
            "WHERE org_id = %s AND model_name = %s AND enabled = TRUE",
            (org_id, name),
        )

    def upsert_policy(
        self, org_id: str, name: str, base: str, policy_text: str, display: str
    ) -> int:
        import psycopg.errors

        self.ensure_org_catalog(org_id)
        base_spec = self.get_modelspec(org_id, base)
        if base_spec is None:
            raise KeyError(f"unknown model spec '{base}'")

        # Retry on uniqueness conflict so concurrent writers across connections
        # converge instead of surfacing a 500.
        last_exc: Optional[BaseException] = None
        for _ in range(_POLICY_VERSION_RETRIES):
            try:
                with self._transaction() as conn:
                    # Transaction-scoped advisory lock serializes version alloc
                    # for this (org, policy) across processes sharing the DB.
                    conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                        (org_id, name),
                    )
                    row = conn.execute(
                        "SELECT COALESCE(MAX(version), 0) AS v FROM policies "
                        "WHERE org_id = %s AND name = %s",
                        (org_id, name),
                    ).fetchone()
                    version = int(row["v"]) + 1
                    conn.execute(
                        "INSERT INTO policies "
                        "(org_id, name, version, base, base_version, "
                        "policy_text, display, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            org_id,
                            name,
                            version,
                            base,
                            base_spec.version,
                            policy_text,
                            display,
                            time.time(),
                        ),
                    )
                return version
            except psycopg.errors.UniqueViolation as exc:
                last_exc = exc
                continue
        raise DuplicateError(
            f"could not allocate policy version for '{name}'"
        ) from last_exc

    def delete_policies(self, org_id: str, name: str) -> None:
        with self._transaction() as conn:
            conn.execute(
                "DELETE FROM policies WHERE org_id = %s AND name = %s",
                (org_id, name),
            )
