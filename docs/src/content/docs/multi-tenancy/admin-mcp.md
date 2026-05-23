---
title: Admin MCP server
description: How to expose the harnessapi tenant management API as MCP tools so agents can manage skill variants natively through Claude Desktop or Claude Code.
---

The admin MCP server exposes the entire multi-tenancy management API as [Model Context Protocol](https://modelcontextprotocol.io) tools. Instead of calling REST endpoints directly, agents — including Claude Desktop, Claude Code, and any custom agent — can manage skill variants natively, as if they were built-in capabilities.

This is the primary interface for **agent-driven skill customization**: an agent can clone a skill, submit modified code, test it, set it to preview, and promote it to production, all through MCP tool calls with no curl commands required.

---

## Enabling the admin MCP server

```python
from harnessapi import HarnessAPI
from harnessapi.multitenancy import TenantBackend, SQLiteStorageBackend

backend = TenantBackend(
    tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
    storage=SQLiteStorageBackend(path="./variants.db"),
)

app = HarnessAPI(
    skills_dir="./skills",
    tenant_backend=backend,
    enable_admin_mcp=True,   # mounts /admin-mcp
)
```

The admin MCP server is mounted at `/admin-mcp` and is separate from the skill MCP server at `/mcp`. The skill MCP server is always tenant-agnostic; the admin MCP server is for management only.

---

## Connecting from Claude Desktop or Claude Code

Add to your MCP config:

```json
{
  "mcpServers": {
    "harnessapi-admin": {
      "url": "http://localhost:8000/admin-mcp"
    }
  }
}
```

All 12 management tools appear immediately. No restart required after adding new skills.

---

## Available tools

| Tool | What it does |
|---|---|
| `clone_skill` | Copy base handler source as a sandbox variant — starting point for customization |
| `customize_skill` | Submit modified handler source — validated before storing |
| `run_variant` | Test a variant with input — forwards to sandbox if provisioned, otherwise runs in-process |
| `preview_variant` | Route real tenant traffic through a variant without full promotion |
| `promote_variant` | Make a variant the active handler for a tenant (demotes previous promoted) |
| `demote_variant` | Move a promoted or preview variant back to sandbox |
| `get_variant_source` | Read the current handler source for any variant |
| `list_tenant_skills` | List all variants for a tenant across all skills |
| `provision_sandbox` | Boot a per-tenant sandbox process |
| `teardown_sandbox` | Shut down a tenant's sandbox |
| `sandbox_health` | Check if a sandbox is reachable and responding |
| `push_to_sandbox` | Deploy the promoted variant's handler source to the sandbox |

---

## Example agent workflow (MCP tools only)

```
1. clone_skill       → variant_id returned (sandbox status)
2. customize_skill   → submit modified source, validated + stored
3. run_variant       → test with sample input, verify output
4. preview_variant   → variant routes real traffic for the tenant (optional staging)
5. promote_variant   → variant becomes permanent active handler
6. push_to_sandbox   → if tenant has a sandbox, sync the promoted handler to it
```

From the agent's perspective, this is a fully self-contained loop — no HTTP client needed, no manual endpoint construction.

---

## Protecting /admin-mcp

> **Security:** The admin MCP server has no authentication by default. Every tool can execute validated code on your server and manage any tenant's variants. You must protect `/admin-mcp` before enabling in production. Never expose it on a public network without auth.

Pass an `admin_mcp_auth` callable to `HarnessAPI`. It receives the incoming request and a `call_next` function — return a 4xx response to reject, or `await call_next(request)` to allow:

```python
import os
from starlette.responses import JSONResponse

async def require_api_key(request, call_next):
    if request.headers.get("X-Admin-Key") != os.environ["ADMIN_KEY"]:
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    return await call_next(request)

app = HarnessAPI(
    skills_dir="./skills",
    tenant_backend=backend,
    enable_admin_mcp=True,
    admin_mcp_auth=require_api_key,
)
```

The signature is `async (request, call_next) -> Response`. Any async callable works — use JWT verification, IP allowlisting, mTLS checks, or any other mechanism.

### Connecting with auth from Claude Desktop

```json
{
  "mcpServers": {
    "harnessapi-admin": {
      "url": "http://localhost:8000/admin-mcp",
      "headers": {
        "X-Admin-Key": "your-secret-key"
      }
    }
  }
}
```

---

## Relationship to the skill MCP server (`/mcp`)

| | `/mcp` | `/admin-mcp` |
|---|---|---|
| Purpose | Exposes skills as tools for end users | Exposes management API for operators/agents |
| Tenant context | None — always base skills | Fully tenant-aware |
| Auth | No built-in auth | Via `admin_mcp_auth` |
| Enabled | Always | Only when `enable_admin_mcp=True` |

---

## See also

- [Multi-tenancy overview](/harnessapi/multi-tenancy/index) — how routing works
- [Variant lifecycle](/harnessapi/multi-tenancy/variants) — full clone → promote workflow
- [Preview & staging](/harnessapi/multi-tenancy/preview) — `preview_variant` tool in context
- [Per-user sandboxes](/harnessapi/multi-tenancy/sandboxes) — `provision_sandbox`, `push_to_sandbox` tools
- [API reference](/harnessapi/multi-tenancy/api-reference) — REST endpoints underlying each MCP tool
