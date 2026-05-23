---
title: API reference
description: Complete endpoint list and TenantBackend configuration reference for harnessapi multi-tenancy.
---

## Management endpoints

All management endpoints are added automatically when a `tenant_backend` is passed to `HarnessAPI`. They are in addition to the normal skill endpoints (`POST /skills/{name}`).

### Variant lifecycle

| Method | Path | Description |
|---|---|---|
| `POST` | `/tenants/{tenant_id}/skills/{name}/clone` | Copy base handler source as a new sandbox variant |
| `POST` | `/tenants/{tenant_id}/skills/{name}/customize` | Submit handler source — validate, store, optionally promote |
| `POST` | `/tenants/{tenant_id}/skills/{name}/variants/{id}/preview` | Set as preview — routes real traffic, coexists with promoted |
| `POST` | `/tenants/{tenant_id}/skills/{name}/variants/{id}/promote` | Make variant active for tenant (demotes previous promoted) |
| `POST` | `/tenants/{tenant_id}/skills/{name}/variants/{id}/demote` | Move back to sandbox status |
| `POST` | `/tenants/{tenant_id}/skills/{name}/variants/{id}/run` | Test with input — forwards to sandbox if provisioned, else in-process |
| `DELETE` | `/tenants/{tenant_id}/skills/{name}/variants/{id}` | Delete variant permanently |

### Introspection

| Method | Path | Description |
|---|---|---|
| `GET` | `/tenants/{tenant_id}/skills` | List all variants for a tenant (all skills) |
| `GET` | `/tenants/{tenant_id}/skills/{name}/variants` | List variants for a specific skill |
| `GET` | `/tenants/{tenant_id}/skills/{name}/variants/{id}/source` | Get handler source for a variant |

### Sandbox lifecycle

Available only when `sandbox_registry` is set in `TenantBackend`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/tenants/{tenant_id}/sandbox/provision` | Boot a sandbox process for the tenant |
| `DELETE` | `/tenants/{tenant_id}/sandbox` | Tear down the tenant's sandbox |
| `GET` | `/tenants/{tenant_id}/sandbox/health` | Health check — returns status and last_seen timestamp |
| `POST` | `/tenants/{tenant_id}/skills/{name}/push-to-sandbox` | Push promoted variant handler source to sandbox |

---

## `customize` request body

```json
{
  "source_code": "async def handle(input: Input) -> Output: ...",
  "auto_promote": false
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `source_code` | `string` | required | Handler source — must pass AST validation |
| `auto_promote` | `bool` | `false` | If `true`, promote immediately after storing |

---

## `provision` request body

```json
{
  "skills_dir": "./skills"
}
```

---

## TenantBackend configuration

```python
from harnessapi.multitenancy import TenantBackend, SQLiteStorageBackend, SandboxRegistry

backend = TenantBackend(
    # Required
    tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),

    # Storage (default: InProcessStorageBackend — ephemeral)
    storage=SQLiteStorageBackend(path="./variants.db"),

    # Validation
    sandbox_import_blocklist=["os", "subprocess", "socket", "sys", "importlib", "builtins"],

    # Behaviour
    auto_promote=False,                    # promote immediately on customize
    max_variants_per_tenant_per_skill=10,  # 409 Conflict when exceeded
    sandbox_run_timeout_secs=10.0,         # timeout for /run and sandbox-forwarded calls

    # Per-tenant sandboxes (optional)
    sandbox_registry=SandboxRegistry(),
    sandbox_provider="local_subprocess",   # or "docker", "kubernetes", or a custom instance
    sandbox_provider_config={},            # passed as kwargs to provider.provision()
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tenant_extractor` | `Callable[[Request], str \| None]` | required | Extracts tenant ID from each request. Return `None` to route to base skill. |
| `storage` | `StorageBackend` | `InProcessStorageBackend()` | Where variants are persisted. |
| `sandbox_import_blocklist` | `list[str]` | `["os", "subprocess", "socket", "sys", "importlib", "builtins"]` | Imports blocked by AST validation. |
| `auto_promote` | `bool` | `False` | If `True`, variants are promoted immediately on customize. |
| `max_variants_per_tenant_per_skill` | `int` | `10` | Maximum sandbox variants per (tenant, skill). Returns `409` when exceeded. |
| `sandbox_run_timeout_secs` | `float` | `10.0` | Timeout in seconds for `/run` and sandbox-forwarded skill calls. |
| `sandbox_registry` | `SandboxRegistry \| None` | `None` | In-memory map of running sandbox connections. Required to enable per-tenant sandboxes. |
| `sandbox_provider` | `str \| SandboxProvider` | `None` | Provider to use when provisioning sandboxes. Strings: `"local_subprocess"`, `"docker"`, `"kubernetes"`. |
| `sandbox_provider_config` | `dict` | `{}` | Extra kwargs forwarded to `provider.provision()`. |

---

## HarnessAPI multi-tenancy parameters

```python
app = HarnessAPI(
    skills_dir="./skills",
    tenant_backend=backend,       # enables multi-tenancy
    enable_admin_mcp=True,        # mounts /admin-mcp
    admin_mcp_auth=require_api_key,  # protects /admin-mcp
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tenant_backend` | `TenantBackend \| None` | `None` | Enables multi-tenancy and the `/tenants/*` management API. |
| `enable_admin_mcp` | `bool` | `False` | Mounts the admin MCP server at `/admin-mcp`. |
| `admin_mcp_auth` | `Callable \| None` | `None` | Async middleware for `/admin-mcp`. Signature: `async (request, call_next) -> Response`. |

---

## Complete setup example

```python
import os
from pathlib import Path
from starlette.responses import JSONResponse
from harnessapi import HarnessAPI
from harnessapi.multitenancy import TenantBackend, SQLiteStorageBackend, SandboxRegistry

async def require_api_key(request, call_next):
    if request.headers.get("X-Admin-Key") != os.environ["ADMIN_KEY"]:
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    return await call_next(request)

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
    admin_mcp_auth=require_api_key,
)
```

---

## See also

- [Multi-tenancy overview](/harnessapi/multi-tenancy/index) — routing resolution order, drop-in setup
- [Variant lifecycle](/harnessapi/multi-tenancy/variants) — clone → promote workflow
- [Preview & staging](/harnessapi/multi-tenancy/preview) — preview endpoint behavior
- [Per-user sandboxes](/harnessapi/multi-tenancy/sandboxes) — sandbox workflow and providers
- [Storage backends](/harnessapi/multi-tenancy/storage) — backend options and custom protocol
- [Admin MCP server](/harnessapi/multi-tenancy/admin-mcp) — MCP tools for each endpoint
