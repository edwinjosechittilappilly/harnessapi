"""Integration tests — tenant routing, clone, customize, run, promote, demote, delete."""
from pathlib import Path

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


async def _post_skill(client, skill_name, payload, tenant_id=None, accept_json=True):
    headers = {}
    if accept_json:
        headers["Accept"] = "application/json"
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    return await client.post(f"/skills/{skill_name}", json=payload, headers=headers)


# ---------------------------------------------------------------------------
# 1. Base skill routing
# ---------------------------------------------------------------------------

async def test_base_skill_no_tenant(client):
    r = await _post_skill(client, "greet", {"name": "World"})
    assert r.status_code == 200
    assert r.json()["message"] == "Hello, World!"


async def test_base_skill_unknown_tenant_uses_base(client):
    r = await _post_skill(client, "greet", {"name": "Alice"}, tenant_id="no-variant")
    assert r.status_code == 200
    assert r.json()["message"] == "Hello, Alice!"


# ---------------------------------------------------------------------------
# 2. Clone
# ---------------------------------------------------------------------------

async def test_clone_returns_base_source(client):
    r = await client.post("/tenants/user-a/skills/greet/clone")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "sandbox"
    assert data["tenant_id"] == "user-a"
    assert data["base_skill_name"] == "greet"
    assert "variant_id" in data
    assert "handle" in data.get("source_code", "")


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
# 4. Run variant in-process
# ---------------------------------------------------------------------------

async def test_run_variant_in_process(client):
    r1 = await client.post(
        "/tenants/user-c/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE},
    )
    variant_id = r1.json()["variant_id"]

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
        json={},
    )
    assert r2.status_code == 422


async def test_run_variant_not_found(client):
    r = await client.post(
        "/tenants/user-x/skills/greet/variants/deadbeef-0000-0000-0000-000000000000/run",
        json={"name": "Test"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 5. Promote
# ---------------------------------------------------------------------------

async def test_promote_routes_tenant_to_variant(client):
    r1 = await client.post(
        "/tenants/user-d/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE},
    )
    variant_id = r1.json()["variant_id"]

    r2 = await client.post(f"/tenants/user-d/skills/greet/variants/{variant_id}/promote")
    assert r2.status_code == 200
    assert r2.json()["status"] == "promoted"

    r3 = await _post_skill(client, "greet", {"name": "Dave"}, tenant_id="user-d")
    assert r3.status_code == 200
    assert r3.json()["message"] == "Howdy, Dave!"


async def test_other_tenant_unaffected_after_promotion(client):
    r1 = await client.post(
        "/tenants/user-e/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE, "auto_promote": True},
    )
    assert r1.json()["status"] == "promoted"

    r2 = await _post_skill(client, "greet", {"name": "Frank"}, tenant_id="user-f")
    assert r2.json()["message"] == "Hello, Frank!"

    r3 = await _post_skill(client, "greet", {"name": "NoTenant"})
    assert r3.json()["message"] == "Hello, NoTenant!"


# ---------------------------------------------------------------------------
# 6. Auto-promote
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
# 7. Demote
# ---------------------------------------------------------------------------

async def test_demote_reverts_to_base_handler(client):
    r1 = await client.post(
        "/tenants/user-g/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE, "auto_promote": True},
    )
    variant_id = r1.json()["variant_id"]

    r2 = await _post_skill(client, "greet", {"name": "Grace"}, tenant_id="user-g")
    assert r2.json()["message"] == "Howdy, Grace!"

    r3 = await client.post(f"/tenants/user-g/skills/greet/variants/{variant_id}/demote")
    assert r3.status_code == 200
    assert r3.json()["status"] == "sandbox"

    r4 = await _post_skill(client, "greet", {"name": "Grace"}, tenant_id="user-g")
    assert r4.json()["message"] == "Hello, Grace!"


# ---------------------------------------------------------------------------
# 8. Second promote auto-demotes previous
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

    r2 = await client.delete(f"/tenants/user-del/skills/greet/variants/{variant_id}")
    assert r2.status_code == 200
    assert r2.json()["deleted"] == variant_id

    assert backend.registry.get_variant(variant_id) is None
