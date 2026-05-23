---
title: Storage backends
description: How harnessapi persists skill variants and sandbox connections across server restarts, and how to choose or implement a storage backend.
---

Variants created and promoted during a server session need to survive restarts. harnessapi uses a pluggable **storage backend** to persist variant source code and status. On startup, promoted and preview variants are loaded from storage, recompiled, and registered — so routing resumes exactly where it left off.

---

## Choosing a backend

| Backend | Persistence | Best for |
|---|---|---|
| `InProcessStorageBackend` | None (memory only) | Development, testing |
| `LocalFileStorageBackend` | JSON files in a directory | Single-worker, no database |
| `SQLiteStorageBackend` | SQLite file | Single-worker production |
| Custom (implement the protocol) | Whatever you need | PostgreSQL, Redis, DynamoDB, etc. |

---

## InProcessStorageBackend

The default when no `storage` argument is passed to `TenantBackend`. Variants are kept in a plain Python dict and disappear when the process exits.

```python
from harnessapi.multitenancy import TenantBackend, InProcessStorageBackend

backend = TenantBackend(
    tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
    storage=InProcessStorageBackend(),  # default — can be omitted
)
```

Use this for local development and tests where persistence is not needed.

---

## LocalFileStorageBackend

Writes one JSON file per variant to a directory. No database required. Files survive process restarts and can be inspected or backed up with standard file tools.

```python
from harnessapi.multitenancy import TenantBackend, LocalFileStorageBackend

backend = TenantBackend(
    tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
    storage=LocalFileStorageBackend(variants_dir="./variants"),
)
```

Each variant is stored as `./variants/{variant_id}.json`. The file contains the full variant record including source code, status, tenant ID, and timestamps.

**Limitations:** No atomic transactions, no concurrent-write safety. Suitable for single-worker deployments only.

---

## SQLiteStorageBackend

Persistent SQLite-backed storage using Python's stdlib `sqlite3` — no extra dependencies. In addition to variants, it also persists sandbox connection metadata (endpoint URL, pid, auth token) so sandbox registrations survive restarts.

```python
from harnessapi.multitenancy import TenantBackend, SQLiteStorageBackend

backend = TenantBackend(
    tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
    storage=SQLiteStorageBackend(path="./variants.db"),
)
```

The database is created automatically on first use. Schema:

- `skill_variant` table — stores variant records. Status constrained to `sandbox | preview | promoted`.
- `sandbox_connection` table — stores sandbox metadata (only populated when `sandbox_registry` is set).

**Limitations:** SQLite's write-lock model makes this unsuitable for multi-worker deployments (multiple Uvicorn/Gunicorn workers writing simultaneously). Use a networked database for multi-worker setups.

---

## Custom backend

Implement the `StorageBackend` protocol — a structural protocol, no base class required:

```python
class MyPostgresBackend:
    async def save_variant(self, variant) -> None: ...
    async def load_promoted_variants(self) -> list: ...
    async def load_preview_variants(self) -> list: ...
    async def load_sandbox_variant(self, variant_id: str): ...
    async def delete_variant(self, variant_id: str) -> None: ...
    async def promote_variant(self, variant_id: str) -> None: ...
    async def demote_variant(self, variant_id: str) -> None: ...
    async def preview_variant(self, variant_id: str) -> None: ...
    async def list_variants(self, tenant_id: str) -> list: ...
```

All methods are async. `load_promoted_variants` and `load_preview_variants` are called at startup to restore active routing. `load_sandbox_variant` is called on-demand to retrieve a specific sandbox-status variant for testing.

Pass your instance directly:

```python
backend = TenantBackend(
    tenant_extractor=...,
    storage=MyPostgresBackend(dsn=os.environ["DATABASE_URL"]),
)
```

---

## Startup restore behavior

When the server starts, harnessapi calls `storage.load_promoted_variants()` and `storage.load_preview_variants()`. For each returned variant it:

1. Compiles the stored handler source into a live function
2. Registers it in the in-memory `TenantSkillRegistry` under the appropriate key

This means a server restart is transparent to callers — active routing resumes immediately without any re-promotion step.

---

## See also

- [Per-user sandboxes](/harnessapi/multi-tenancy/sandboxes) — SQLite backend also stores sandbox connection metadata
- [API reference](/harnessapi/multi-tenancy/api-reference) — TenantBackend configuration reference
