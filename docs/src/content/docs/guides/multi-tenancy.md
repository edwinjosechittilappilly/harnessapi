---
title: Multi-tenancy & per-user skill variants
description: Let each user own a customized version of any skill — same schema, different implementation — with one line added to HarnessAPI.
---

harnessapi has a built-in multi-tenancy layer. Add one parameter to `HarnessAPI(...)` and every skill automatically supports per-user variants: same input/output schema, different handler implementation, isolated routing.

This is the foundation for **agent-driven skill customization** — users (or the agents acting on their behalf) submit modified handler code via HTTP, test it in a sandbox, and promote it when ready. No restarts, no deploys, no per-tenant route tables.

---

## How it works

```
POST /skills/greet   (X-Tenant-ID: user-a)
         │
         ▼
   SkillRoute resolves:
   1. Does user-a have a promoted variant?  → use variant handler
   2. Does user-a have a sandbox?           → forward to sandbox process
   3. No variant, no sandbox               → use base skill handler
```

The route table never grows. Dispatch is a single dict lookup per request.

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

## Agent workflow: clone → customize → test → promote

This is the standard pattern for an external agent (Claude Code, a custom agent, any HTTP client) to customize a skill for a user.

### Step 1 — Clone the base skill

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/clone
```

```json
{
  "variant_id": "3f2a1...",
  "tenant_id": "user-a",
  "base_skill_name": "greet",
  "status": "sandbox",
  "source_code": "async def handle(input: Input) -> Output:\n    return Output(message=f'Hello, {input.name}!')"
}
```

The response includes the base handler source as a starting point. The agent modifies it locally.

### Step 2 — Submit customized source

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/customize \
  -H "Content-Type: application/json" \
  -d '{
    "source_code": "async def handle(input: Input) -> Output:\n    return Output(message=f\"Howdy, {input.name}!\")"
  }'
```

harnessapi validates the source (AST checks — no dangerous imports, correct function signature) before accepting it. Invalid code returns a `422` with a list of violations.

### Step 3 — Test in sandbox

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/variants/3f2a1.../run \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice"}'
```

```json
{"message": "Howdy, Alice!"}
```

The variant runs in-process with a configurable timeout. Errors are returned as structured JSON — the variant is never live for production traffic at this stage.

### Step 4 — Promote

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/variants/3f2a1.../promote
```

All subsequent `POST /skills/greet` requests with `X-Tenant-ID: user-a` now use the promoted handler. Other tenants and calls without a tenant header still use the base skill.

---

## Auto-promote shortcut

Skip the explicit promote step by passing `auto_promote: true` on customize:

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/customize \
  -d '{"source_code": "...", "auto_promote": true}'
```

Or set it as the default on the backend:

```python
backend = TenantBackend(
    ...,
    auto_promote=True,
)
```

---

## Handler source constraints

Submitted handler source must pass static AST validation before it is accepted:

| Rule | What it blocks |
|---|---|
| No blocked imports | `os`, `subprocess`, `socket`, `sys`, `importlib`, `builtins` (configurable) |
| No dangerous builtins | `exec`, `eval`, `compile`, `open`, `__import__` |
| Exactly one top-level async function | Must be named `handle` |
| One positional parameter | `handle(input)` |

```python
# Valid
async def handle(input: Input) -> Output:
    return Output(message=input.name.upper())

# Also valid — streaming
async def handle(input: Input):
    for word in input.text.split():
        yield word

# Rejected — blocked import
import os
async def handle(input): ...

# Rejected — wrong function name
async def process(input): ...
```

Customize the blocklist per deployment:

```python
backend = TenantBackend(
    ...,
    sandbox_import_blocklist=["os", "subprocess", "socket"],  # remove sys/importlib if needed
)
```

---

## Per-user sandboxes

For true process isolation, provision a sandbox for each tenant. Skill calls for that tenant are forwarded to the sandbox process over HTTP instead of running in the main server's process.

```python
from harnessapi.multitenancy import TenantBackend, SQLiteStorageBackend, SandboxRegistry

backend = TenantBackend(
    tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
    storage=SQLiteStorageBackend(path="./variants.db"),
    sandbox_registry=SandboxRegistry(),
    sandbox_provider="local_subprocess",   # or "docker" or "kubernetes"
)
```

### Provision a sandbox

```bash
curl -X POST http://localhost:8000/tenants/user-a/sandbox/provision \
  -d '{"skills_dir": "./skills"}'
```

```json
{
  "tenant_id": "user-a",
  "endpoint_url": "http://127.0.0.1:43721",
  "sandbox_type": "local_subprocess",
  "pid": 9182,
  "status": "running"
}
```

### Push variant and call it

```bash
# Push the promoted variant to the sandbox
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/push-to-sandbox

# Skill call is now forwarded to the sandbox automatically
curl -X POST http://localhost:8000/skills/greet \
  -H "X-Tenant-ID: user-a" \
  -d '{"name": "Alice"}'
```

### Check sandbox health

```bash
curl http://localhost:8000/tenants/user-a/sandbox/health
```

```json
{"status": "healthy", "endpoint_url": "http://127.0.0.1:43721", "last_seen": "2026-05-22T19:00:00Z"}
```

### Tear down

```bash
curl -X DELETE http://localhost:8000/tenants/user-a/sandbox
```

### Sandbox providers

| Provider string | What it does | Extra deps |
|---|---|---|
| `"local_subprocess"` | Spawns a Python subprocess on a random local port | none |
| `"docker"` | Runs a Docker container | `pip install harnessapi[docker]` |
| `"kubernetes"` | Creates a Pod + Service | `pip install harnessapi[kubernetes]` |

You can also pass a custom provider instance directly:

```python
backend = TenantBackend(
    ...,
    sandbox_registry=SandboxRegistry(),
    sandbox_provider=MyCustomProvider(),   # any object implementing SandboxProvider protocol
)
```

The `SandboxProvider` protocol:

```python
class SandboxProvider(Protocol):
    sandbox_type: str
    async def provision(self, tenant_id: str, skills_dir: str, **kwargs) -> SandboxConnection: ...
    async def teardown(self, conn: SandboxConnection) -> None: ...
```

---

## Admin MCP server

Expose the entire management API as MCP tools so agents can manage skill variants natively through Claude Desktop or Claude Code — no curl required.

```python
app = HarnessAPI(
    skills_dir="./skills",
    tenant_backend=backend,
    enable_admin_mcp=True,   # mounts /admin-mcp
)
```

Add to Claude Desktop or Claude Code:

```json
{
  "mcpServers": {
    "harnessapi-admin": {
      "url": "http://localhost:8000/admin-mcp"
    }
  }
}
```

Available MCP tools:

| Tool | What it does |
|---|---|
| `clone_skill` | Copy base handler source as starting point |
| `customize_skill` | Submit and validate modified handler source |
| `promote_variant` | Make a variant the active handler for a tenant |
| `demote_variant` | Move a promoted variant back to sandbox |
| `run_variant` | Test a variant with input (sandbox or in-process) |
| `get_variant_source` | Read current handler source for a variant |
| `list_tenant_skills` | List all variants for a tenant |
| `provision_sandbox` | Boot a per-tenant sandbox process |
| `teardown_sandbox` | Shut down a sandbox |
| `sandbox_health` | Check if a sandbox is reachable |
| `push_to_sandbox` | Deploy promoted variant handler to the sandbox |

> The admin MCP server has no authentication by default. Add auth middleware before enabling in production.

---

## Storage backends

| Backend | Persistence | When to use |
|---|---|---|
| `InProcessStorageBackend` | None (memory only) | Dev, testing |
| `SQLiteStorageBackend` | SQLite file | Single-worker production |
| Custom (implement the protocol) | Whatever you need | Postgres, Redis, etc. |

Variants survive server restarts with `SQLiteStorageBackend` — promoted variants are reloaded and recompiled at startup.

**Custom backend example (Postgres):**

```python
class PostgresStorageBackend:
    async def save_variant(self, variant): ...
    async def load_promoted_variants(self): ...
    async def load_sandbox_variant(self, variant_id): ...
    async def delete_variant(self, variant_id): ...
    async def promote_variant(self, variant_id): ...
    async def demote_variant(self, variant_id): ...
    async def list_variants(self, tenant_id): ...
```

No base class required — structural protocol.

---

## Full management API reference

### Variant lifecycle

| Method | Path | Description |
|---|---|---|
| `POST` | `/tenants/{tenant_id}/skills/{name}/clone` | Copy base source as sandbox variant |
| `POST` | `/tenants/{tenant_id}/skills/{name}/customize` | Submit source → validate → store |
| `POST` | `/tenants/{tenant_id}/skills/{name}/variants/{id}/promote` | Make variant active for tenant |
| `POST` | `/tenants/{tenant_id}/skills/{name}/variants/{id}/demote` | Move back to sandbox |
| `POST` | `/tenants/{tenant_id}/skills/{name}/variants/{id}/run` | Test with input (returns output or error) |
| `DELETE` | `/tenants/{tenant_id}/skills/{name}/variants/{id}` | Delete variant |

### Introspection

| Method | Path | Description |
|---|---|---|
| `GET` | `/tenants/{tenant_id}/skills` | List all variants for tenant |
| `GET` | `/tenants/{tenant_id}/skills/{name}/variants` | List variants for a specific skill |
| `GET` | `/tenants/{tenant_id}/skills/{name}/variants/{id}/source` | Get handler source |

### Sandbox lifecycle (only when `sandbox_registry` is set)

| Method | Path | Description |
|---|---|---|
| `POST` | `/tenants/{tenant_id}/sandbox/provision` | Boot sandbox |
| `DELETE` | `/tenants/{tenant_id}/sandbox` | Tear down sandbox |
| `GET` | `/tenants/{tenant_id}/sandbox/health` | Health check |
| `POST` | `/tenants/{tenant_id}/skills/{name}/push-to-sandbox` | Push variant source to sandbox |

---

## TenantBackend configuration

```python
TenantBackend(
    # Required
    tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),

    # Storage (default: InProcessStorageBackend)
    storage=SQLiteStorageBackend(path="./variants.db"),

    # Validation
    sandbox_import_blocklist=["os", "subprocess", "socket", "sys", "importlib", "builtins"],

    # Behaviour
    auto_promote=False,                    # promote immediately on customize
    max_variants_per_tenant_per_skill=10,  # 409 when exceeded
    sandbox_run_timeout_secs=10.0,         # timeout for /run and sandbox forwards

    # Per-tenant sandboxes (optional)
    sandbox_registry=SandboxRegistry(),
    sandbox_provider="local_subprocess",   # or "docker", "kubernetes", or a custom instance
    sandbox_provider_config={},            # passed to provider.provision()
)
```

---

## Complete example

```python
from pathlib import Path
from harnessapi import HarnessAPI
from harnessapi.multitenancy import TenantBackend, SQLiteStorageBackend, SandboxRegistry

backend = TenantBackend(
    tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
    storage=SQLiteStorageBackend(path="./variants.db"),
    sandbox_registry=SandboxRegistry(),
    sandbox_provider="local_subprocess",
    auto_promote=False,
    max_variants_per_tenant_per_skill=5,
    sandbox_run_timeout_secs=10.0,
)

app = HarnessAPI(
    skills_dir=Path(__file__).parent / "skills",
    tenant_backend=backend,
    enable_admin_mcp=True,
)
```

With this config an agent can:

1. Call `provision_sandbox` (MCP) → sandbox is running
2. Call `customize_skill` (MCP) → variant validated and stored
3. Call `run_variant` (MCP) → test input forwarded to sandbox
4. Call `promote_variant` (MCP) → variant goes live for the tenant
5. `POST /skills/{name}` with `X-Tenant-ID` → routed to the sandbox running the promoted variant
