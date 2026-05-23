"""Integration tests for the multi-tenancy layer.

Scenario: a 'greet' skill exists as the base. Tenants can clone it, customize
the handler, test in a sandbox variant, promote, and have their call routed to
the promoted variant. Other tenants still get the base handler.
"""
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from harnessapi import HarnessAPI
from harnessapi.multitenancy import (
    TenantBackend,
    InProcessStorageBackend,
    TenantSkillRegistry,
)

SKILLS_DIR = Path(__file__).parent / "skills"

# ---------------------------------------------------------------------------
# Shared custom handler source used across tests
# ---------------------------------------------------------------------------

CUSTOM_GREET_SOURCE = """\
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    name: str

class Output(SkillOutput):
    message: str

async def handle(input: Input) -> Output:
    return Output(message=f"Howdy, {input.name}!")
"""

STREAMING_GREET_SOURCE = """\
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    name: str

async def handle(input: Input):
    yield f"Hey"
    yield f"{input.name}!"
"""

INVALID_SOURCE_BLOCKED_IMPORT = """\
import os
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    name: str

async def handle(input: Input):
    return None
"""

INVALID_SOURCE_SYNTAX = """\
def broken(:
    pass
"""

INVALID_SOURCE_NO_HANDLE = """\
async def wrong_name(input):
    pass
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def backend():
    return TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
    )


@pytest.fixture
def tenant_app(backend):
    return HarnessAPI(
        skills_dir=SKILLS_DIR,
        tenant_backend=backend,
        enable_edit_endpoints=True,
    )


@pytest.fixture
async def client(tenant_app):
    async with AsyncClient(
        transport=ASGITransport(app=tenant_app), base_url="http://test"
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _post_skill(client, skill_name, payload, tenant_id=None, accept_json=True):
    headers = {}
    if accept_json:
        headers["Accept"] = "application/json"
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    return await client.post(f"/skills/{skill_name}", json=payload, headers=headers)


# ---------------------------------------------------------------------------
# 1. Base skill still works when no tenant is set
# ---------------------------------------------------------------------------

async def test_base_skill_no_tenant(client):
    r = await _post_skill(client, "greet", {"name": "World"})
    assert r.status_code == 200
    assert r.json()["message"] == "Hello, World!"


async def test_base_skill_unknown_tenant_uses_base(client):
    """A tenant with no variant falls through to the base handler."""
    r = await _post_skill(client, "greet", {"name": "Alice"}, tenant_id="no-variant")
    assert r.status_code == 200
    assert r.json()["message"] == "Hello, Alice!"


# ---------------------------------------------------------------------------
# 2. Clone — returns base source
# ---------------------------------------------------------------------------

async def test_clone_returns_base_source(client):
    r = await client.post("/tenants/user-a/skills/greet/clone")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "sandbox"
    assert data["tenant_id"] == "user-a"
    assert data["base_skill_name"] == "greet"
    assert "variant_id" in data
    assert "handle" in data.get("source_code", "")  # base handler has a handle fn


async def test_clone_unknown_skill_404(client):
    r = await client.post("/tenants/user-a/skills/nonexistent/clone")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3. Customize — validate + store variant
# ---------------------------------------------------------------------------

async def test_customize_creates_sandbox_variant(client):
    r = await client.post(
        "/tenants/user-b/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "sandbox"
    assert data["tenant_id"] == "user-b"
    assert "variant_id" in data


async def test_customize_blocked_import_422(client):
    r = await client.post(
        "/tenants/user-b/skills/greet/customize",
        json={"source_code": INVALID_SOURCE_BLOCKED_IMPORT},
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "violations" in detail or "os" in str(detail)


async def test_customize_syntax_error_422(client):
    r = await client.post(
        "/tenants/user-b/skills/greet/customize",
        json={"source_code": INVALID_SOURCE_SYNTAX},
    )
    assert r.status_code == 422


async def test_customize_no_handle_fn_422(client):
    r = await client.post(
        "/tenants/user-b/skills/greet/customize",
        json={"source_code": INVALID_SOURCE_NO_HANDLE},
    )
    assert r.status_code == 422


async def test_customize_empty_source_422(client):
    r = await client.post(
        "/tenants/user-b/skills/greet/customize",
        json={"source_code": "   "},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 4. Run (sandbox test — in-process when no sandbox provisioned)
# ---------------------------------------------------------------------------

async def test_run_variant_in_process(client):
    # Create variant
    r1 = await client.post(
        "/tenants/user-c/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE},
    )
    variant_id = r1.json()["variant_id"]

    # Run it
    r2 = await client.post(
        f"/tenants/user-c/skills/greet/variants/{variant_id}/run",
        json={"name": "TestUser"},
    )
    assert r2.status_code == 200
    assert r2.json()["message"] == "Howdy, TestUser!"


async def test_run_variant_invalid_input(client):
    r1 = await client.post(
        "/tenants/user-c/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE},
    )
    variant_id = r1.json()["variant_id"]

    r2 = await client.post(
        f"/tenants/user-c/skills/greet/variants/{variant_id}/run",
        json={},  # missing required 'name' field
    )
    assert r2.status_code == 422


async def test_run_variant_not_found(client):
    r = await client.post(
        "/tenants/user-x/skills/greet/variants/deadbeef-0000-0000-0000-000000000000/run",
        json={"name": "Test"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 5. Promote — variant becomes active for tenant
# ---------------------------------------------------------------------------

async def test_promote_routes_tenant_to_variant(client):
    # Customize
    r1 = await client.post(
        "/tenants/user-d/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE},
    )
    variant_id = r1.json()["variant_id"]

    # Promote
    r2 = await client.post(
        f"/tenants/user-d/skills/greet/variants/{variant_id}/promote"
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "promoted"

    # Tenant call now uses custom handler
    r3 = await _post_skill(client, "greet", {"name": "Dave"}, tenant_id="user-d")
    assert r3.status_code == 200
    assert r3.json()["message"] == "Howdy, Dave!"


async def test_other_tenant_unaffected_after_promotion(client):
    """Promoting a variant for user-e must not affect user-f (or no-tenant)."""
    # Promote for user-e
    r1 = await client.post(
        "/tenants/user-e/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE, "auto_promote": True},
    )
    assert r1.json()["status"] == "promoted"

    # user-f still gets base
    r2 = await _post_skill(client, "greet", {"name": "Frank"}, tenant_id="user-f")
    assert r2.json()["message"] == "Hello, Frank!"

    # No tenant still gets base
    r3 = await _post_skill(client, "greet", {"name": "NoTenant"})
    assert r3.json()["message"] == "Hello, NoTenant!"


# ---------------------------------------------------------------------------
# 6. Auto-promote via customize
# ---------------------------------------------------------------------------

async def test_auto_promote_on_customize(client):
    r = await client.post(
        "/tenants/user-ap/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE, "auto_promote": True},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "promoted"

    r2 = await _post_skill(client, "greet", {"name": "AutoPromo"}, tenant_id="user-ap")
    assert r2.json()["message"] == "Howdy, AutoPromo!"


# ---------------------------------------------------------------------------
# 7. Demote — falls back to base
# ---------------------------------------------------------------------------

async def test_demote_reverts_to_base_handler(client):
    # Promote
    r1 = await client.post(
        "/tenants/user-g/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE, "auto_promote": True},
    )
    variant_id = r1.json()["variant_id"]

    # Confirm promoted
    r2 = await _post_skill(client, "greet", {"name": "Grace"}, tenant_id="user-g")
    assert r2.json()["message"] == "Howdy, Grace!"

    # Demote
    r3 = await client.post(
        f"/tenants/user-g/skills/greet/variants/{variant_id}/demote"
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "sandbox"

    # Now back to base
    r4 = await _post_skill(client, "greet", {"name": "Grace"}, tenant_id="user-g")
    assert r4.json()["message"] == "Hello, Grace!"


# ---------------------------------------------------------------------------
# 8. Promoting new variant auto-demotes previous
# ---------------------------------------------------------------------------

async def test_second_promote_demotes_first(client):
    custom_v2 = CUSTOM_GREET_SOURCE.replace("Howdy", "Greetings")

    r1 = await client.post(
        "/tenants/user-h/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE, "auto_promote": True},
    )
    assert r1.json()["status"] == "promoted"

    r2 = await client.post(
        "/tenants/user-h/skills/greet/customize",
        json={"source_code": custom_v2, "auto_promote": True},
    )
    assert r2.json()["status"] == "promoted"

    # Latest promoted variant is active
    r3 = await _post_skill(client, "greet", {"name": "Hannah"}, tenant_id="user-h")
    assert r3.json()["message"] == "Greetings, Hannah!"


# ---------------------------------------------------------------------------
# 9. Delete variant
# ---------------------------------------------------------------------------

async def test_delete_variant(client, backend):
    r1 = await client.post(
        "/tenants/user-del/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE},
    )
    variant_id = r1.json()["variant_id"]

    r2 = await client.delete(
        f"/tenants/user-del/skills/greet/variants/{variant_id}"
    )
    assert r2.status_code == 200
    assert r2.json()["deleted"] == variant_id

    # Variant is gone from registry
    assert backend.registry.get_variant(variant_id) is None


# ---------------------------------------------------------------------------
# 10. List endpoints
# ---------------------------------------------------------------------------

async def test_list_tenant_skills(client):
    await client.post(
        "/tenants/user-list/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE},
    )
    r = await client.get("/tenants/user-list/skills")
    assert r.status_code == 200
    variants = r.json()
    assert len(variants) >= 1
    assert any(v["base_skill_name"] == "greet" for v in variants)


async def test_list_skill_variants(client):
    await client.post(
        "/tenants/user-lv/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE},
    )
    r = await client.get("/tenants/user-lv/skills/greet/variants")
    assert r.status_code == 200
    variants = r.json()
    assert len(variants) >= 1
    assert all(v["base_skill_name"] == "greet" for v in variants)


async def test_list_skill_variants_unknown_skill_404(client):
    r = await client.get("/tenants/user-lv/skills/noskill/variants")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 11. Get variant source
# ---------------------------------------------------------------------------

async def test_get_variant_source(client):
    r1 = await client.post(
        "/tenants/user-src/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE},
    )
    variant_id = r1.json()["variant_id"]

    r2 = await client.get(
        f"/tenants/user-src/skills/greet/variants/{variant_id}/source"
    )
    assert r2.status_code == 200
    assert "Howdy" in r2.json()["source_code"]


# ---------------------------------------------------------------------------
# 12. Variant max limit
# ---------------------------------------------------------------------------

async def test_max_variants_per_tenant_per_skill():
    small_backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
        max_variants_per_tenant_per_skill=2,
    )
    app = HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=small_backend)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for _ in range(2):
            r = await c.post(
                "/tenants/user-max/skills/greet/customize",
                json={"source_code": CUSTOM_GREET_SOURCE},
            )
            assert r.status_code == 200

        # Third one should be rejected
        r = await c.post(
            "/tenants/user-max/skills/greet/customize",
            json={"source_code": CUSTOM_GREET_SOURCE},
        )
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# 13. Streaming variant via SSE
# ---------------------------------------------------------------------------

async def test_streaming_variant_sse(client):
    r1 = await client.post(
        "/tenants/user-sse/skills/greet/customize",
        json={"source_code": STREAMING_GREET_SOURCE, "auto_promote": True},
    )
    assert r1.json()["status"] == "promoted"

    # SSE call (no Accept: application/json)
    r2 = await client.post(
        "/skills/greet",
        json={"name": "StreamUser"},
        headers={"X-Tenant-ID": "user-sse"},
    )
    assert r2.status_code == 200
    text = r2.text
    assert "Hey" in text
    assert "StreamUser!" in text
    assert "event: done" in text


async def test_streaming_variant_json_collects_chunks(client):
    r1 = await client.post(
        "/tenants/user-sj/skills/greet/customize",
        json={"source_code": STREAMING_GREET_SOURCE, "auto_promote": True},
    )
    assert r1.json()["status"] == "promoted"

    r2 = await client.post(
        "/skills/greet",
        json={"name": "ChunkUser"},
        headers={"X-Tenant-ID": "user-sj", "Accept": "application/json"},
    )
    assert r2.status_code == 200
    chunks = r2.json()["chunks"]
    assert "Hey" in chunks
    assert "ChunkUser!" in chunks


# ---------------------------------------------------------------------------
# 14. Storage persistence (SQLite round-trip)
# ---------------------------------------------------------------------------

async def test_sqlite_storage_saves_and_loads_promoted_variant(tmp_path):
    """Variants saved to SQLite appear in load_promoted_variants."""
    from harnessapi.multitenancy import SQLiteStorageBackend
    from harnessapi.multitenancy.models import SkillVariant
    from harnessapi.multitenancy.sandbox import compile_variant_handler
    from datetime import datetime, timezone
    from harnessapi.models import SkillInput, SkillOutput

    class _In(SkillInput):
        name: str

    class _Out(SkillOutput):
        message: str

    storage = SQLiteStorageBackend(path=tmp_path / "test.db")
    handler = compile_variant_handler(CUSTOM_GREET_SOURCE, "greet", "sql-vid")
    variant = SkillVariant(
        variant_id="sql-vid",
        tenant_id="persist-user",
        base_skill_name="greet",
        handler_source=CUSTOM_GREET_SOURCE,
        handler=handler,
        status="sandbox",
        created_at=datetime.now(timezone.utc),
        input_model=_In,
        output_model=_Out,
    )
    await storage.save_variant(variant)
    await storage.promote_variant("sql-vid")

    promoted = await storage.load_promoted_variants()
    ids = [p.variant_id for p in promoted]
    assert "sql-vid" in ids


async def test_sqlite_storage_demote_removes_from_promoted(tmp_path):
    from harnessapi.multitenancy import SQLiteStorageBackend
    from harnessapi.multitenancy.models import SkillVariant
    from harnessapi.multitenancy.sandbox import compile_variant_handler
    from datetime import datetime, timezone
    from harnessapi.models import SkillInput, SkillOutput

    class _In(SkillInput):
        name: str

    class _Out(SkillOutput):
        message: str

    storage = SQLiteStorageBackend(path=tmp_path / "test2.db")
    handler = compile_variant_handler(CUSTOM_GREET_SOURCE, "greet", "sql-v2")
    variant = SkillVariant(
        variant_id="sql-v2",
        tenant_id="persist-user",
        base_skill_name="greet",
        handler_source=CUSTOM_GREET_SOURCE,
        handler=handler,
        status="sandbox",
        created_at=datetime.now(timezone.utc),
        input_model=_In,
        output_model=_Out,
    )
    await storage.save_variant(variant)
    await storage.promote_variant("sql-v2")
    await storage.demote_variant("sql-v2")

    promoted = await storage.load_promoted_variants()
    ids = [p.variant_id for p in promoted]
    assert "sql-v2" not in ids


async def test_inprocess_storage_is_ephemeral(backend):
    """InProcessStorageBackend always returns empty from load_promoted_variants — it's ephemeral by design."""
    promoted = await backend.storage.load_promoted_variants()
    assert promoted == []


# ---------------------------------------------------------------------------
# 15. Admin MCP server is mounted when enabled
# ---------------------------------------------------------------------------

def test_admin_mcp_mounted_when_enabled():
    """The /admin-mcp mount appears in the route table when enable_admin_mcp=True."""
    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
    )
    app = HarnessAPI(
        skills_dir=SKILLS_DIR,
        tenant_backend=backend,
        enable_admin_mcp=True,
    )
    from starlette.routing import Mount
    mount_paths = [r.path for r in app.routes if isinstance(r, Mount)]
    assert "/admin-mcp" in mount_paths


def test_admin_mcp_not_mounted_when_disabled():
    """No /admin-mcp mount when enable_admin_mcp=False (default)."""
    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
    )
    app = HarnessAPI(
        skills_dir=SKILLS_DIR,
        tenant_backend=backend,
        enable_admin_mcp=False,
    )
    from starlette.routing import Mount
    mount_paths = [r.path for r in app.routes if isinstance(r, Mount)]
    assert "/admin-mcp" not in mount_paths


def test_admin_mcp_not_mounted_without_tenant_backend():
    """enable_admin_mcp=True has no effect without a tenant_backend."""
    app = HarnessAPI(
        skills_dir=SKILLS_DIR,
        enable_admin_mcp=True,
    )
    from starlette.routing import Mount
    mount_paths = [r.path for r in app.routes if isinstance(r, Mount)]
    assert "/admin-mcp" not in mount_paths
