---
title: Per-user sandboxes
description: How to provision isolated per-tenant sandbox processes for full code execution isolation in harnessapi.
---

By default, variant handlers execute in the main server process. This is fast and simple but means all tenants share a process boundary — a misbehaving handler can affect others.

**Per-user sandboxes** fix this: each tenant gets their own isolated process (subprocess, Docker container, or Kubernetes pod). Skill calls for that tenant are proxied to the sandbox over HTTP instead of running in-process.

---

## When to use sandboxes

| Use case | Approach |
|---|---|
| Trusted users, internal tools | In-process promoted variants (no sandbox needed) |
| Untrusted or user-submitted code | Sandbox — provides process isolation |
| Strict resource limits per tenant | Sandbox — apply CPU/memory limits at the container/pod level |
| Compliance or audit requirements | Sandbox — each tenant's execution is fully isolated |

AST validation alone is not a security boundary. If users can submit arbitrary handler code, provision a sandbox.

---

## Setup

Add `sandbox_registry` and `sandbox_provider` to `TenantBackend`:

```python
from harnessapi.multitenancy import TenantBackend, SQLiteStorageBackend, SandboxRegistry

backend = TenantBackend(
    tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
    storage=SQLiteStorageBackend(path="./variants.db"),
    sandbox_registry=SandboxRegistry(),
    sandbox_provider="local_subprocess",   # or "docker" or "kubernetes"
)

app = HarnessAPI(skills_dir="./skills", tenant_backend=backend)
```

`SandboxRegistry` is the in-memory map from tenant IDs to running sandbox connections. It is created fresh on startup; persistent sandbox state (endpoint URL, pid, etc.) is stored in the storage backend.

---

## Sandbox workflow

### 1. Provision a sandbox

```bash
curl -X POST http://localhost:8000/tenants/user-a/sandbox/provision \
  -H "Content-Type: application/json" \
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

The sandbox starts a fresh harnessapi server with the base skills loaded. It is reachable only from the main server — never directly exposed.

### 2. Push a variant to the sandbox

After promoting a variant, push its handler source to the sandbox so the sandbox runs the customized version:

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/push-to-sandbox
```

harnessapi only sends the HTTP request if the handler source has changed since the last push (source-level deduplication). Repeated calls are cheap.

### 3. Call the skill — automatically forwarded

```bash
curl -X POST http://localhost:8000/skills/greet \
  -H "X-Tenant-ID: user-a" \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice"}'
```

The main server detects that `user-a` has a sandbox and proxies the request. The response comes back through the main server — callers see no difference.

### 4. Check sandbox health

```bash
curl http://localhost:8000/tenants/user-a/sandbox/health
```

```json
{
  "status": "healthy",
  "endpoint_url": "http://127.0.0.1:43721",
  "last_seen": "2026-05-22T19:00:00Z"
}
```

### 5. Tear down

```bash
curl -X DELETE http://localhost:8000/tenants/user-a/sandbox
```

Stops the sandbox process and removes its registration. Subsequent calls fall back to in-process promoted or base handler.

---

## Sandbox providers

| Provider string | What it does | Extra deps |
|---|---|---|
| `"local_subprocess"` | Spawns a Python subprocess on a random local port | none |
| `"docker"` | Runs a Docker container | `pip install harnessapi[docker]` |
| `"kubernetes"` | Creates a Pod + ClusterIP Service | `pip install harnessapi[kubernetes]` |

### Custom provider

Pass any object that implements the `SandboxProvider` protocol:

```python
from harnessapi.multitenancy import SandboxRegistry

backend = TenantBackend(
    ...,
    sandbox_registry=SandboxRegistry(),
    sandbox_provider=MyCustomProvider(),
)
```

The protocol:

```python
class SandboxProvider(Protocol):
    sandbox_type: str

    async def provision(
        self,
        tenant_id: str,
        skills_dir: str,
        **kwargs,
    ) -> SandboxConnection: ...

    async def teardown(self, conn: SandboxConnection) -> None: ...
```

`SandboxConnection` is a dataclass with `tenant_id`, `endpoint_url`, `sandbox_type`, `pid`, `auth_token`, `metadata`, `created_at`, and `last_seen`.

---

## Push deduplication

`push-to-sandbox` tracks the last pushed handler source per skill in memory on the `SandboxConnection` object. If the source has not changed since the last successful push, the HTTP call is skipped entirely. This makes it safe to call `push-to-sandbox` eagerly without worrying about redundant network traffic.

The cache is in-memory only — it resets if the main server restarts. The first push after a restart will always send.

---

## Provider-specific configuration

Pass extra kwargs to `provision()` via `sandbox_provider_config`:

```python
backend = TenantBackend(
    ...,
    sandbox_provider="docker",
    sandbox_provider_config={
        "image": "my-org/harnessapi-sandbox:latest",
        "memory_limit": "512m",
        "cpu_period": 100000,
        "cpu_quota": 50000,
    },
)
```

---

## See also

- [Storage backends](/harnessapi/multi-tenancy/storage) — SQLite backend also persists sandbox connection metadata
- [Admin MCP server](/harnessapi/multi-tenancy/admin-mcp) — `provision_sandbox`, `teardown_sandbox`, `push_to_sandbox` MCP tools
- [API reference](/harnessapi/multi-tenancy/api-reference) — sandbox endpoint list
