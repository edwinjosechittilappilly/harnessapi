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
    async def load_sandbox_variant(self, variant_id: str) -> SkillVariant | None: ...
    async def delete_variant(self, variant_id: str) -> None: ...
    async def promote_variant(self, variant_id: str) -> None: ...
    async def demote_variant(self, variant_id: str) -> None: ...
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
    status            TEXT NOT NULL CHECK(status IN ('sandbox','promoted')),
    created_at        TEXT NOT NULL,
    meta_overrides_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_tenant_skill
    ON skill_variant(tenant_id, base_skill_name, status);
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

    async def list_variants(self, tenant_id: str) -> list[SkillVariant]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_variant WHERE tenant_id=?", (tenant_id,)
            ).fetchall()
        return [_row_to_partial_variant(row) for row in rows]


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
