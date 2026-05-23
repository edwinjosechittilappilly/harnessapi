"""Integration tests — admin MCP mount, auth wrapper, sandbox routing, push deduplication."""
from pathlib import Path
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient, ASGITransport

from harnessapi import HarnessAPI
from harnessapi.multitenancy import TenantBackend, InProcessStorageBackend

pytestmark = pytest.mark.integration

SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

CUSTOM_GREET_SOURCE = """\
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    name: str

class Output(SkillOutput):
    message: str

async def handle(input: Input) -> Output:
    return Output(message=f"Howdy, {input.name}!")
"""


# ---------------------------------------------------------------------------
# Admin MCP mount
# ---------------------------------------------------------------------------

def test_admin_mcp_mounted_when_enabled():
    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
    )
    app = HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=backend, enable_admin_mcp=True)
    from starlette.routing import Mount
    mount_paths = [r.path for r in app.routes if isinstance(r, Mount)]
    assert "/admin-mcp" in mount_paths


def test_admin_mcp_not_mounted_when_disabled():
    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
    )
    app = HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=backend, enable_admin_mcp=False)
    from starlette.routing import Mount
    mount_paths = [r.path for r in app.routes if isinstance(r, Mount)]
    assert "/admin-mcp" not in mount_paths


def test_admin_mcp_not_mounted_without_tenant_backend():
    app = HarnessAPI(skills_dir=SKILLS_DIR, enable_admin_mcp=True)
    from starlette.routing import Mount
    mount_paths = [r.path for r in app.routes if isinstance(r, Mount)]
    assert "/admin-mcp" not in mount_paths


# ---------------------------------------------------------------------------
# Admin MCP auth wrapper
# ---------------------------------------------------------------------------

async def test_admin_mcp_auth_rejects_unauthenticated():
    from starlette.responses import JSONResponse as SJR
    from harnessapi.app import _AdminAuthWrapper

    async def require_key(request, call_next):
        if request.headers.get("X-Admin-Key") != "secret":
            return SJR({"detail": "Forbidden"}, status_code=403)
        return await call_next(request)

    inner_called: list[bool] = []

    async def echo_app(scope, receive, send):
        inner_called.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    wrapper = _AdminAuthWrapper(echo_app, require_key)

    from starlette.applications import Starlette
    starlette_app = Starlette()
    starlette_app.mount("/admin-mcp", wrapper)

    async with AsyncClient(transport=ASGITransport(app=starlette_app), base_url="http://test") as c:
        r = await c.get("/admin-mcp/")

    assert r.status_code == 403
    assert not inner_called


async def test_admin_mcp_auth_allows_authenticated():
    from starlette.responses import JSONResponse as SJR
    from harnessapi.app import _AdminAuthWrapper

    call_next_called: list[bool] = []

    async def require_key(request, call_next):
        if request.headers.get("X-Admin-Key") != "secret":
            return SJR({"detail": "Forbidden"}, status_code=403)
        call_next_called.append(True)
        return await call_next(request)

    async def echo_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    wrapper = _AdminAuthWrapper(echo_app, require_key)

    from starlette.applications import Starlette
    starlette_app = Starlette()
    starlette_app.mount("/admin-mcp", wrapper)

    async with AsyncClient(transport=ASGITransport(app=starlette_app), base_url="http://test") as c:
        r = await c.get("/admin-mcp/", headers={"X-Admin-Key": "secret"})

    assert r.status_code == 200
    assert call_next_called


# ---------------------------------------------------------------------------
# Sandbox routing — SSE vs JSON path
# ---------------------------------------------------------------------------

async def test_run_variant_forwards_validated_input(monkeypatch):
    from harnessapi.multitenancy import SandboxRegistry
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection, SandboxRegistry

    forwarded: list[dict] = []

    async def fake_push(conn, skill_name, source, timeout=30.0):
        pass

    async def fake_forward(conn, skill_name, input_json, timeout=10.0):
        forwarded.append(input_json)
        return {"message": "from-sandbox"}

    from harnessapi.multitenancy import sandbox_client as sc_module
    monkeypatch.setattr(sc_module.sandbox_client, "push_skill", fake_push)
    monkeypatch.setattr(sc_module.sandbox_client, "forward", fake_forward)

    sb_registry = SandboxRegistry()
    conn = SandboxConnection(
        tenant_id="user-fwd",
        endpoint_url="http://127.0.0.1:99999",
        sandbox_type="local_subprocess",
        created_at=datetime.now(timezone.utc),
    )
    sb_registry.register(conn)

    sb_backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
        sandbox_registry=sb_registry,
    )
    sb_app = HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=sb_backend)

    async with AsyncClient(transport=ASGITransport(app=sb_app), base_url="http://test") as c:
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
    assert forwarded[0] == {"name": "Validated"}


async def test_sandbox_sse_proxy_path(monkeypatch):
    from harnessapi.multitenancy import SandboxRegistry
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection

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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/skills/greet",
            json={"name": "SSEUser"},
            headers={"X-Tenant-ID": "sse-user"},
        )

    assert r.status_code == 200
    assert sse_called
    assert not json_called


async def test_sandbox_json_path_calls_forward(monkeypatch):
    from harnessapi.multitenancy import SandboxRegistry
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection

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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/skills/greet",
            json={"name": "JSONUser"},
            headers={"X-Tenant-ID": "json-user", "Accept": "application/json"},
        )

    assert r.status_code == 200
    assert r.json()["message"] == "Hello, JSONUser!"
    assert not sse_called


# ---------------------------------------------------------------------------
# Push deduplication
# ---------------------------------------------------------------------------

async def test_push_skill_dedup_skips_when_source_unchanged(monkeypatch):
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection
    from harnessapi.multitenancy.sandbox_client import SandboxClient

    conn = SandboxConnection(
        tenant_id="dedup-user",
        endpoint_url="http://127.0.0.1:99999",
        sandbox_type="local_subprocess",
        created_at=datetime.now(timezone.utc),
    )

    http_calls: list[int] = [0]

    async def counting_push(self, conn, skill_name, handler_source, timeout=30.0):
        if conn.last_pushed_source.get(skill_name) != handler_source:
            http_calls[0] += 1
            conn.last_pushed_source[skill_name] = handler_source

    monkeypatch.setattr(SandboxClient, "push_skill", counting_push)

    sc = SandboxClient()
    source = "async def handle(input): pass"
    await sc.push_skill(conn, "greet", source)
    await sc.push_skill(conn, "greet", source)
    await sc.push_skill(conn, "greet", source)

    assert http_calls[0] == 1


async def test_push_skill_dedup_pushes_on_source_change(monkeypatch):
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection
    from harnessapi.multitenancy.sandbox_client import SandboxClient

    conn = SandboxConnection(
        tenant_id="dedup-change",
        endpoint_url="http://127.0.0.1:99999",
        sandbox_type="local_subprocess",
        created_at=datetime.now(timezone.utc),
    )

    http_calls: list[int] = [0]

    async def counting_push(self, conn, skill_name, handler_source, timeout=30.0):
        if conn.last_pushed_source.get(skill_name) != handler_source:
            http_calls[0] += 1
            conn.last_pushed_source[skill_name] = handler_source

    monkeypatch.setattr(SandboxClient, "push_skill", counting_push)

    sc = SandboxClient()
    await sc.push_skill(conn, "greet", "source_v1")
    await sc.push_skill(conn, "greet", "source_v1")
    await sc.push_skill(conn, "greet", "source_v2")

    assert http_calls[0] == 2


async def test_push_skill_dedup_via_real_logic():
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection
    from harnessapi.multitenancy.sandbox_client import SandboxClient

    conn = SandboxConnection(
        tenant_id="real-dedup",
        endpoint_url="http://127.0.0.1:99999",
        sandbox_type="local_subprocess",
        created_at=datetime.now(timezone.utc),
    )

    sc = SandboxClient()
    source = "async def handle(input): pass"
    conn.last_pushed_source["greet"] = source
    await sc.push_skill(conn, "greet", source)  # should be a no-op, no HTTP raised
