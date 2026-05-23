from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import SkillVariant


# ---------------------------------------------------------------------------
# Protocol (structural — no ABC required; operators can implement their own)
# ---------------------------------------------------------------------------

class StorageBackend:
    """Structural protocol. Implement all methods to provide a custom backend."""

    async def save_variant(self, variant: SkillVariant) -> None: ...
    async def load_promoted_variants(self) -> list[SkillVariant]: ...
    async def load_preview_variants(self) -> list[SkillVariant]: ...
    async def load_sandbox_variant(self, variant_id: str) -> SkillVariant | None: ...
    async def delete_variant(self, variant_id: str) -> None: ...
    async def promote_variant(self, variant_id: str) -> None: ...
    async def demote_variant(self, variant_id: str) -> None: ...
    async def preview_variant(self, variant_id: str) -> None: ...
    async def list_variants(self, tenant_id: str) -> list[SkillVariant]: ...


# ---------------------------------------------------------------------------
# In-process (ephemeral — dev/test)
# ---------------------------------------------------------------------------

class InProcessStorageBackend(StorageBackend):
    """Stores variants only in memory. No persistence across restarts."""

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}  # variant_id → serialised dict

    async def save_variant(self, variant: SkillVariant) -> None:
        self._store[variant.variant_id] = _variant_to_dict(variant)

    async def load_promoted_variants(self) -> list[SkillVariant]:
        return []  # nothing to restore; registry is in-memory only

    async def load_preview_variants(self) -> list[SkillVariant]:
        return []

    async def load_sandbox_variant(self, variant_id: str) -> SkillVariant | None:
        return None

    async def delete_variant(self, variant_id: str) -> None:
        self._store.pop(variant_id, None)

    async def promote_variant(self, variant_id: str) -> None:
        if variant_id in self._store:
            self._store[variant_id]["status"] = "promoted"

    async def demote_variant(self, variant_id: str) -> None:
        if variant_id in self._store:
            self._store[variant_id]["status"] = "sandbox"

    async def preview_variant(self, variant_id: str) -> None:
        if variant_id in self._store:
            self._store[variant_id]["status"] = "preview"

    async def list_variants(self, tenant_id: str) -> list[SkillVariant]:
        return []


# ---------------------------------------------------------------------------
# SQLite (persistent, single-process)
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS skill_variant (
    variant_id        TEXT PRIMARY KEY,
    tenant_id         TEXT NOT NULL,
    base_skill_name   TEXT NOT NULL,
    handler_source    TEXT NOT NULL,
    status            TEXT NOT NULL CHECK(status IN ('sandbox','preview','promoted')),
    created_at        TEXT NOT NULL,
    meta_overrides_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_tenant_skill
    ON skill_variant(tenant_id, base_skill_name, status);

CREATE TABLE IF NOT EXISTS sandbox_connection (
    tenant_id    TEXT PRIMARY KEY,
    endpoint_url TEXT NOT NULL,
    sandbox_type TEXT NOT NULL,
    pid          INTEGER,
    auth_token   TEXT,
    metadata_json TEXT DEFAULT '{}',
    created_at   TEXT NOT NULL,
    last_seen    TEXT
);
"""


class SQLiteStorageBackend(StorageBackend):
    """Persistent SQLite-backed storage. Uses stdlib sqlite3, no extra deps."""

    def __init__(self, path: str | Path = "./variants.db") -> None:
        self._path = str(path)
        conn = sqlite3.connect(self._path)
        conn.executescript(_DDL)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    async def save_variant(self, variant: SkillVariant) -> None:
        d = _variant_to_dict(variant)
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO skill_variant
                   (variant_id, tenant_id, base_skill_name, handler_source,
                    status, created_at, meta_overrides_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    d["variant_id"], d["tenant_id"], d["base_skill_name"],
                    d["handler_source"], d["status"], d["created_at"],
                    json.dumps(d.get("meta_overrides", {})),
                ),
            )

    async def load_promoted_variants(self) -> list[SkillVariant]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_variant WHERE status='promoted'"
            ).fetchall()
        return [_row_to_partial_variant(row) for row in rows]

    async def load_preview_variants(self) -> list[SkillVariant]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_variant WHERE status='preview'"
            ).fetchall()
        return [_row_to_partial_variant(row) for row in rows]

    async def load_sandbox_variant(self, variant_id: str) -> SkillVariant | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM skill_variant WHERE variant_id=? AND status='sandbox'",
                (variant_id,),
            ).fetchone()
        return _row_to_partial_variant(row) if row else None

    async def delete_variant(self, variant_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM skill_variant WHERE variant_id=?", (variant_id,))

    async def promote_variant(self, variant_id: str) -> None:
        with self._conn() as conn:
            # demote any existing promoted variant for same (tenant, skill)
            row = conn.execute(
                "SELECT tenant_id, base_skill_name FROM skill_variant WHERE variant_id=?",
                (variant_id,),
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE skill_variant SET status='sandbox'
                       WHERE tenant_id=? AND base_skill_name=? AND status='promoted'""",
                    (row["tenant_id"], row["base_skill_name"]),
                )
            conn.execute(
                "UPDATE skill_variant SET status='promoted' WHERE variant_id=?",
                (variant_id,),
            )

    async def demote_variant(self, variant_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE skill_variant SET status='sandbox' WHERE variant_id=?",
                (variant_id,),
            )

    async def preview_variant(self, variant_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE skill_variant SET status='preview' WHERE variant_id=?",
                (variant_id,),
            )

    async def list_variants(self, tenant_id: str) -> list[SkillVariant]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_variant WHERE tenant_id=?", (tenant_id,)
            ).fetchall()
        return [_row_to_partial_variant(row) for row in rows]

    # ------------------------------------------------------------------
    # Sandbox connection persistence
    # ------------------------------------------------------------------

    async def save_sandbox(self, conn_obj) -> None:
        """Persist a SandboxConnection. conn_obj is a SandboxConnection dataclass."""
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sandbox_connection
                   (tenant_id, endpoint_url, sandbox_type, pid, auth_token,
                    metadata_json, created_at, last_seen)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    conn_obj.tenant_id,
                    conn_obj.endpoint_url,
                    conn_obj.sandbox_type,
                    conn_obj.pid,
                    conn_obj.auth_token,
                    json.dumps(conn_obj.metadata),
                    conn_obj.created_at.isoformat(),
                    conn_obj.last_seen.isoformat() if conn_obj.last_seen else None,
                ),
            )

    async def load_sandboxes(self) -> list:
        """Load all persisted sandbox connections as raw dicts (no live process state)."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM sandbox_connection").fetchall()
        return [_row_to_sandbox_dict(row) for row in rows]

    async def update_sandbox_last_seen(self, tenant_id: str, ts: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE sandbox_connection SET last_seen=? WHERE tenant_id=?",
                (ts, tenant_id),
            )

    async def delete_sandbox(self, tenant_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sandbox_connection WHERE tenant_id=?", (tenant_id,))


# ---------------------------------------------------------------------------
# Local file (persistent, single-worker, no DB deps)
# ---------------------------------------------------------------------------

class LocalFileStorageBackend(StorageBackend):
    """File-per-variant JSON storage under a directory. No extra deps — stdlib only."""

    def __init__(self, variants_dir: str | Path) -> None:
        self._dir = Path(variants_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, variant_id: str) -> Path:
        return self._dir / f"{variant_id}.json"

    def _read(self, variant_id: str) -> dict | None:
        p = self._path(variant_id)
        if not p.exists():
            return None
        return json.loads(p.read_text())

    def _write(self, data: dict) -> None:
        self._path(data["variant_id"]).write_text(json.dumps(data))

    async def save_variant(self, variant: SkillVariant) -> None:
        self._write(_variant_to_dict(variant))

    async def load_promoted_variants(self) -> list[_PartialVariant]:
        result = []
        for p in self._dir.glob("*.json"):
            try:
                data = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("status") == "promoted":
                result.append(_dict_to_partial_variant(data))
        return result

    async def load_preview_variants(self) -> list[_PartialVariant]:
        result = []
        for p in self._dir.glob("*.json"):
            try:
                data = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("status") == "preview":
                result.append(_dict_to_partial_variant(data))
        return result

    async def load_sandbox_variant(self, variant_id: str) -> _PartialVariant | None:
        data = self._read(variant_id)
        if data is None or data.get("status") not in ("sandbox", "preview"):
            return None
        return _dict_to_partial_variant(data)

    async def delete_variant(self, variant_id: str) -> None:
        self._path(variant_id).unlink(missing_ok=True)

    async def promote_variant(self, variant_id: str) -> None:
        data = self._read(variant_id)
        if data is not None:
            data["status"] = "promoted"
            self._write(data)

    async def demote_variant(self, variant_id: str) -> None:
        data = self._read(variant_id)
        if data is not None:
            data["status"] = "sandbox"
            self._write(data)

    async def preview_variant(self, variant_id: str) -> None:
        data = self._read(variant_id)
        if data is not None:
            data["status"] = "preview"
            self._write(data)

    async def list_variants(self, tenant_id: str) -> list[_PartialVariant]:
        result = []
        for p in self._dir.glob("*.json"):
            try:
                data = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("tenant_id") == tenant_id:
                result.append(_dict_to_partial_variant(data))
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _variant_to_dict(variant: SkillVariant) -> dict:
    return {
        "variant_id": variant.variant_id,
        "tenant_id": variant.tenant_id,
        "base_skill_name": variant.base_skill_name,
        "handler_source": variant.handler_source,
        "status": variant.status,
        "created_at": variant.created_at.isoformat(),
        "meta_overrides": variant.meta_overrides,
    }


class _PartialVariant:
    """Thin container for rows loaded from storage (no compiled handler yet).

    The router's startup loader compiles handlers after loading from storage.
    """
    def __init__(
        self,
        variant_id: str,
        tenant_id: str,
        base_skill_name: str,
        handler_source: str,
        status: str,
        created_at: str,
        meta_overrides: dict,
    ) -> None:
        self.variant_id = variant_id
        self.tenant_id = tenant_id
        self.base_skill_name = base_skill_name
        self.handler_source = handler_source
        self.status = status
        self.created_at_str = created_at
        self.meta_overrides = meta_overrides


def _row_to_partial_variant(row) -> _PartialVariant:
    return _PartialVariant(
        variant_id=row["variant_id"],
        tenant_id=row["tenant_id"],
        base_skill_name=row["base_skill_name"],
        handler_source=row["handler_source"],
        status=row["status"],
        created_at=row["created_at"],
        meta_overrides=json.loads(row["meta_overrides_json"] or "{}"),
    )


def _dict_to_partial_variant(data: dict) -> _PartialVariant:
    return _PartialVariant(
        variant_id=data["variant_id"],
        tenant_id=data["tenant_id"],
        base_skill_name=data["base_skill_name"],
        handler_source=data["handler_source"],
        status=data["status"],
        created_at=data["created_at"],
        meta_overrides=data.get("meta_overrides", {}),
    )


def _row_to_sandbox_dict(row) -> dict:
    return {
        "tenant_id": row["tenant_id"],
        "endpoint_url": row["endpoint_url"],
        "sandbox_type": row["sandbox_type"],
        "pid": row["pid"],
        "auth_token": row["auth_token"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "created_at": row["created_at"],
        "last_seen": row["last_seen"],
    }
