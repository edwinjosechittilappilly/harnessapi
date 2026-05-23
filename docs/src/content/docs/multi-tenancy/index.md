---
title: Multi-tenancy overview
description: How harnessapi lets every user own a customized version of any skill — same schema, different implementation, isolated routing — with one line added to HarnessAPI.
---

harnessapi has a built-in multi-tenancy layer. Add one parameter to `HarnessAPI(...)` and every skill automatically supports per-user variants: same input/output schema, different handler implementation, isolated routing.

This is the foundation for **agent-driven skill customization** — users (or the agents acting on their behalf) submit modified handler code via HTTP, test it in a sandbox, and promote it when ready. No restarts, no deploys, no per-tenant route tables.

---

## How routing works

Every `POST /skills/{name}` request goes through a four-step resolution:

```
POST /skills/greet   (X-Tenant-ID: user-a)
         │
         ▼
   SkillRoute resolves:
   1. Does user-a have a sandbox?           → forward entire request to sandbox process
   2. Does user-a have a preview variant?   → run preview handler in-process
   3. Does user-a have a promoted variant?  → run variant handler in-process
   4. No variant, no sandbox               → use base skill handler
```

The route table never grows — dispatch is a single dict lookup per request, regardless of how many tenants or variants exist. Requests without a tenant header always reach the base skill.

**What each step means:**

- **Sandbox** — the tenant has a provisioned process (subprocess, Docker, Kubernetes). The request is proxied verbatim. The sandbox runs whatever handler was last pushed to it.
- **Preview** — a variant has been set to `preview` status. It routes real tenant traffic without fully replacing the promoted handler. Useful for gradual rollouts and canary testing.
- **Promoted** — the tenant's active variant. Set explicitly by an operator or agent after sandbox testing.
- **Base** — the shared, unmodified skill handler. Used when no tenant context applies.

---

## Drop-in setup

**Before (single-tenant):**
```python
app = HarnessAPI(skills_dir="./skills")
```

**After (multi-tenant — two lines added):**
```python
from harnessapi import HarnessAPI
from harnessapi.multitenancy import TenantBackend, SQLiteStorageBackend

backend = TenantBackend(
    tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
    storage=SQLiteStorageBackend(path="./variants.db"),
)

app = HarnessAPI(skills_dir="./skills", tenant_backend=backend)
```

All existing skill endpoints (`POST /skills/{name}`) continue to work unchanged. harnessapi adds a `/tenants/*` management API automatically.

---

## Core invariants

| Invariant | Why it matters |
|---|---|
| Schema never changes per tenant | `input_model` and `output_model` are always from the base skill. Agents change the handler only. All callers stay schema-compatible. |
| Variants must be explicitly promoted | Sandbox → promoted is a deliberate step. Agents can test before going live. |
| At most one promoted variant per (tenant, skill) | Promoting a new variant automatically demotes the previous one. No stale routing. |
| MCP tools always use base skills | MCP has no tenant context. The `/mcp` endpoint is tenant-agnostic. |

---

## Tenant extraction

The `tenant_extractor` is any callable that reads a request and returns a `str | None`. It can be sync or async:

```python
# From a header (most common)
tenant_extractor=lambda req: req.headers.get("X-Tenant-ID")

# From a JWT sub-claim (async)
async def from_jwt(req):
    token = req.headers.get("Authorization", "").removeprefix("Bearer ")
    return decode_jwt(token).get("sub")

# From a query parameter
tenant_extractor=lambda req: req.query_params.get("tenant")

# From a path segment (useful with API gateways)
tenant_extractor=lambda req: req.path_params.get("tenant_id")
```

When the extractor returns `None`, harnessapi routes to the base skill — no variant lookup.

---

## What's next

| Topic | Page |
|---|---|
| Clone, customize, test, promote a variant | [Variant lifecycle](/harnessapi/multi-tenancy/variants) |
| Route real traffic before hard-promoting | [Preview & staging](/harnessapi/multi-tenancy/preview) |
| True process isolation per tenant | [Per-user sandboxes](/harnessapi/multi-tenancy/sandboxes) |
| Persist variants across restarts | [Storage backends](/harnessapi/multi-tenancy/storage) |
| Agent-native management via MCP tools | [Admin MCP server](/harnessapi/multi-tenancy/admin-mcp) |
| All endpoints and config params | [API reference](/harnessapi/multi-tenancy/api-reference) |
