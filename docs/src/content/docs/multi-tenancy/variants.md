---
title: Variant lifecycle
description: How to clone, customize, validate, test, and promote per-tenant skill variants in harnessapi.
---

A **variant** is a modified version of a base skill handler that belongs to a specific tenant. Variants share the same input/output schema as the base skill — only the handler implementation changes.

Every variant moves through a defined lifecycle before it routes production traffic:

```
clone ──► customize ──► run (test) ──► preview (optional) ──► promote
   │                                                               │
   └─────────────────── sandbox status ───────────────────────────┘
                                                          promoted status
```

---

## Variant statuses

| Status | What it means | Routing |
|---|---|---|
| `sandbox` | Created but not yet active | Only reachable via `/run` — never routes real calls |
| `preview` | Active for real traffic as a canary | Routes real tenant calls; coexists with promoted variant |
| `promoted` | Fully active | Routes all real tenant calls (unless a preview is set) |

At most **one promoted** and **one preview** variant can be active per (tenant, skill) at any time.

---

## Step 1 — Clone the base skill

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

The response includes the base handler source as a starting point. The agent or user modifies it locally before submitting.

---

## Step 2 — Submit customized source

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/customize \
  -H "Content-Type: application/json" \
  -d '{
    "source_code": "async def handle(input: Input) -> Output:\n    return Output(message=f\"Howdy, {input.name}!\")"
  }'
```

harnessapi validates the source (AST checks — no dangerous imports, correct function signature) before accepting it. Invalid code returns a `422` with a list of violations.

---

## Step 3 — Test in sandbox

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/variants/3f2a1.../run \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice"}'
```

```json
{"message": "Howdy, Alice!"}
```

The variant runs with a configurable timeout. Errors are returned as structured JSON — the variant is never live for production traffic at this stage. If the tenant has a sandbox provisioned, the run request is forwarded there; otherwise it executes in-process.

---

## Step 4 — Promote

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/variants/3f2a1.../promote
```

All subsequent `POST /skills/greet` requests with `X-Tenant-ID: user-a` now use the promoted handler. Other tenants and calls without a tenant header still use the base skill.

If a different variant was previously promoted, it is automatically moved back to `sandbox` status.

---

## Optional: Preview before promoting

Between step 3 and step 4, you can set the variant to `preview` status. This routes real tenant calls through it while leaving any existing promoted variant in place. See [Preview & staging](/harnessapi/multi-tenancy/preview) for the full pattern.

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

> **Security note:** AST validation blocks naive mistakes and obvious injection attempts. It is **not** a security boundary — determined code can bypass it (e.g. via `getattr`, `__builtins__`, or lambda tricks). True isolation requires a `SandboxProvider` (subprocess/Docker/Kubernetes). Do not rely on AST validation alone for untrusted input.

Submitted handler source must pass static AST validation before it is accepted:

| Rule | What it blocks |
|---|---|
| No blocked imports | `os`, `subprocess`, `socket`, `sys`, `importlib`, `builtins` (configurable) |
| No dangerous builtins | `exec`, `eval`, `compile`, `open`, `__import__` |
| Exactly one top-level async function | Must be named `handle` |
| One positional parameter | `handle(input)` |

```python
# Valid — non-streaming
async def handle(input: Input) -> Output:
    return Output(message=input.name.upper())

# Valid — streaming
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
    sandbox_import_blocklist=["os", "subprocess", "socket"],  # narrow the list if needed
)
```

---

## Demoting and deleting

Move a promoted variant back to sandbox status:

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/variants/3f2a1.../demote
```

Delete a variant entirely:

```bash
curl -X DELETE http://localhost:8000/tenants/user-a/skills/greet/variants/3f2a1...
```

---

## See also

- [Preview & staging](/harnessapi/multi-tenancy/preview) — route real traffic without committing to promotion
- [Per-user sandboxes](/harnessapi/multi-tenancy/sandboxes) — true process isolation for variant execution
- [API reference](/harnessapi/multi-tenancy/api-reference) — full endpoint list
