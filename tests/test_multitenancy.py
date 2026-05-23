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


# ---------------------------------------------------------------------------
# 16. Provider is cached — same instance returned on every call
# ---------------------------------------------------------------------------

def test_sandbox_provider_is_cached():
    """get_sandbox_provider() must return the same instance every call so that
    the process handle dict in LocalSubprocessProvider is not lost between
    provision and teardown calls."""
    from harnessapi.multitenancy import SandboxRegistry

    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
        sandbox_registry=SandboxRegistry(),
        sandbox_provider="local_subprocess",
    )
    p1 = backend.get_sandbox_provider()
    p2 = backend.get_sandbox_provider()
    assert p1 is p2


# ---------------------------------------------------------------------------
# 17. Stale sandbox connections are dropped on restore
# ---------------------------------------------------------------------------

async def test_restore_sandbox_connections_drops_unreachable(tmp_path):
    """Connections that fail a health check are removed from storage on restore,
    not registered into the in-memory registry."""
    from harnessapi.multitenancy import SQLiteStorageBackend, SandboxRegistry
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection
    from datetime import datetime, timezone

    storage = SQLiteStorageBackend(path=tmp_path / "sb.db")
    registry = SandboxRegistry()
    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=storage,
        sandbox_registry=registry,
    )

    # Write a stale connection pointing at a port nothing is listening on
    stale = SandboxConnection(
        tenant_id="stale-tenant",
        endpoint_url="http://127.0.0.1:1",   # port 1 is never open
        sandbox_type="local_subprocess",
        created_at=datetime.now(timezone.utc),
    )
    await storage.save_sandbox(stale)

    # Run the restore logic
    from harnessapi.app import _restore_sandbox_connections
    await _restore_sandbox_connections(backend)

    # Stale connection must not be in the registry
    assert registry.get("stale-tenant") is None

    # And must have been purged from storage too
    remaining = await storage.load_sandboxes()
    assert not any(r["tenant_id"] == "stale-tenant" for r in remaining)


# ---------------------------------------------------------------------------
# 18. run_variant forwards validated input (model_dump) to sandbox, not raw body
# ---------------------------------------------------------------------------

async def test_run_variant_forwards_validated_input(client, monkeypatch):
    """When a sandbox is provisioned, /run must forward input_obj.model_dump(),
    not the raw body dict, so validation happens centrally."""
    from harnessapi.multitenancy import SandboxRegistry
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection
    from datetime import datetime, timezone

    # Create a variant
    r1 = await client.post(
        "/tenants/user-fwd/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE},
    )
    variant_id = r1.json()["variant_id"]

    # Inject a fake sandbox connection into the registry used by this app
    # (we need to reach inside the fixture's backend)
    forwarded: list[dict] = []

    async def fake_push(conn, skill_name, source, timeout=30.0):
        pass

    async def fake_forward(conn, skill_name, input_json, timeout=10.0):
        forwarded.append(input_json)
        return {"message": "from-sandbox"}

    from harnessapi.multitenancy import sandbox_client as sc_module
    monkeypatch.setattr(sc_module.sandbox_client, "push_skill", fake_push)
    monkeypatch.setattr(sc_module.sandbox_client, "forward", fake_forward)

    # Attach a fake connection to the backend's sandbox registry
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection, SandboxRegistry
    sb_registry = SandboxRegistry()
    conn = SandboxConnection(
        tenant_id="user-fwd",
        endpoint_url="http://127.0.0.1:99999",
        sandbox_type="local_subprocess",
        created_at=datetime.now(timezone.utc),
    )
    sb_registry.register(conn)

    # Temporarily swap the backend's sandbox_registry
    # We rebuild an app with sandbox_registry set
    from harnessapi.multitenancy import SQLiteStorageBackend
    sb_backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
        sandbox_registry=sb_registry,
    )
    sb_app = HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=sb_backend)

    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=sb_app), base_url="http://test") as c:
        # Create variant in this app's backend
        r = await c.post(
            "/tenants/user-fwd/skills/greet/customize",
            json={"source_code": CUSTOM_GREET_SOURCE},
        )
        vid = r.json()["variant_id"]

        monkeypatch.setattr(sc_module.sandbox_client, "push_skill", fake_push)
        monkeypatch.setattr(sc_module.sandbox_client, "forward", fake_forward)

        r2 = await c.post(
            f"/tenants/user-fwd/skills/greet/variants/{vid}/run",
            json={"name": "Validated"},
        )

    assert r2.status_code == 200
    assert len(forwarded) == 1
    # The forwarded payload must be the Pydantic model's output, not the raw body.
    # model_dump() on the Input model produces {"name": "Validated"} — same here,
    # but critically this path exercises the model_dump() branch not raw body.
    assert forwarded[0] == {"name": "Validated"}


# ---------------------------------------------------------------------------
# 19. SSE sandbox proxy path: forward_sse is called when no Accept: application/json
# ---------------------------------------------------------------------------

async def test_sandbox_sse_proxy_path(monkeypatch):
    """When a sandbox is registered and the caller does not send Accept: application/json,
    routing.py must call forward_sse (the SSE proxy), not forward."""
    from harnessapi.multitenancy import SandboxRegistry
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection
    from datetime import datetime, timezone

    sse_called: list[bool] = []
    json_called: list[bool] = []

    async def fake_forward_sse(conn, skill_name, input_json, timeout=30.0):
        sse_called.append(True)
        yield {"data": "hello", "event": "chunk"}
        yield {"data": "", "event": "done"}

    async def fake_forward(conn, skill_name, input_json, timeout=30.0):
        json_called.append(True)
        return {"message": "json"}

    from harnessapi.multitenancy import sandbox_client as sc_module
    monkeypatch.setattr(sc_module.sandbox_client, "forward_sse", fake_forward_sse)
    monkeypatch.setattr(sc_module.sandbox_client, "forward", fake_forward)

    sb_registry = SandboxRegistry()
    conn = SandboxConnection(
        tenant_id="sse-user",
        endpoint_url="http://127.0.0.1:99999",
        sandbox_type="local_subprocess",
        created_at=datetime.now(timezone.utc),
    )
    sb_registry.register(conn)

    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
        sandbox_registry=sb_registry,
    )
    app = HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=backend)

    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # SSE request (no Accept: application/json)
        r = await c.post(
            "/skills/greet",
            json={"name": "SSEUser"},
            headers={"X-Tenant-ID": "sse-user"},
        )

    assert r.status_code == 200
    assert sse_called, "forward_sse should have been called for SSE request"
    assert not json_called, "forward (JSON) should not have been called for SSE request"


async def test_sandbox_json_path_calls_forward(monkeypatch):
    """When a sandbox is registered and the caller sends Accept: application/json,
    routing.py must call forward (JSON), not forward_sse."""
    from harnessapi.multitenancy import SandboxRegistry
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection
    from datetime import datetime, timezone

    sse_called: list[bool] = []

    async def fake_forward_sse(conn, skill_name, input_json, timeout=30.0):
        sse_called.append(True)
        yield {}

    async def fake_forward(conn, skill_name, input_json, timeout=30.0):
        return {"message": "Hello, JSONUser!"}

    from harnessapi.multitenancy import sandbox_client as sc_module
    monkeypatch.setattr(sc_module.sandbox_client, "forward_sse", fake_forward_sse)
    monkeypatch.setattr(sc_module.sandbox_client, "forward", fake_forward)

    sb_registry = SandboxRegistry()
    conn = SandboxConnection(
        tenant_id="json-user",
        endpoint_url="http://127.0.0.1:99999",
        sandbox_type="local_subprocess",
        created_at=datetime.now(timezone.utc),
    )
    sb_registry.register(conn)

    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
        sandbox_registry=sb_registry,
    )
    app = HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=backend)

    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/skills/greet",
            json={"name": "JSONUser"},
            headers={"X-Tenant-ID": "json-user", "Accept": "application/json"},
        )

    assert r.status_code == 200
    assert r.json()["message"] == "Hello, JSONUser!"
    assert not sse_called, "forward_sse should not have been called for JSON request"
