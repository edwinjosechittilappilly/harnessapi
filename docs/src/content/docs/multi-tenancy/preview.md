---
title: Preview & staging
description: How to use preview status to route real tenant traffic through a variant before committing to a full promotion.
---

**Preview** is a variant status between `sandbox` and `promoted`. A preview variant routes real tenant traffic — giving you live exposure without committing to a full promotion. If something goes wrong, you demote it and the previously promoted variant (if any) immediately resumes serving traffic.

This is the recommended staging step for any significant handler change.

---

## How preview coexists with promoted

At most **one preview** and **one promoted** variant can be active per (tenant, skill) simultaneously. Preview takes routing priority:

```
Request (X-Tenant-ID: user-a)
         │
         ▼
   Is there a preview variant?     YES → run preview handler
         │ NO
         ▼
   Is there a promoted variant?    YES → run promoted handler
         │ NO
         ▼
   Use base skill handler
```

Setting a preview does **not** demote any existing promoted variant. Both coexist — the preview is simply checked first.

---

## Setting a variant to preview

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/variants/3f2a1.../preview
```

```json
{
  "variant_id": "3f2a1...",
  "tenant_id": "user-a",
  "base_skill_name": "greet",
  "status": "preview"
}
```

Real calls to `POST /skills/greet` with `X-Tenant-ID: user-a` now hit the preview handler immediately.

---

## Displacement rule

Setting a **new** preview when one already exists for the same (tenant, skill) moves the previous preview back to `sandbox` status automatically. Only one preview is ever active at a time.

```bash
# Variant A is preview
curl -X POST .../variants/variant-a/preview   # variant-a → preview

# Set variant B as preview — variant-a moves back to sandbox
curl -X POST .../variants/variant-b/preview   # variant-b → preview, variant-a → sandbox
```

---

## Typical staging flow

```
1. clone       → create sandbox variant from base handler
2. customize   → submit modified source (validated)
3. run         → test in isolation, no real traffic
4. preview     → real tenant traffic hits the variant (staging)
5. promote     → commit as permanent active handler
```

Steps 1–3 are always safe (no live traffic). Step 4 exposes the variant to real traffic with an easy rollback path. Step 5 commits.

---

## Stopping a preview

**Demote it** (moves back to sandbox, promoted variant — if any — resumes):

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/variants/3f2a1.../demote
```

**Promote a different variant** (clears the preview slot, new variant becomes promoted):

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/variants/other-id.../promote
```

**Promote the preview itself** (moves it from preview to promoted):

```bash
curl -X POST http://localhost:8000/tenants/user-a/skills/greet/variants/3f2a1.../promote
```

---

## Preview via Admin MCP

When the admin MCP server is enabled, the `preview_variant` tool is available directly from Claude Desktop or Claude Code:

```
Tool: preview_variant
Args: { "tenant_id": "user-a", "skill_name": "greet", "variant_id": "3f2a1..." }
```

See [Admin MCP server](/harnessapi/multi-tenancy/admin-mcp) for setup.

---

## See also

- [Variant lifecycle](/harnessapi/multi-tenancy/variants) — full clone → customize → test → promote workflow
- [Admin MCP server](/harnessapi/multi-tenancy/admin-mcp) — manage variants as MCP tools
- [API reference](/harnessapi/multi-tenancy/api-reference) — preview endpoint details
