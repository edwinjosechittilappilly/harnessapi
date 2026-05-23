"""Integration tests — preview variant status, routing priority, coexistence, persistence."""
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

PREVIEW_GREET_SOURCE = """\
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    name: str

class Output(SkillOutput):
    message: str

async def handle(input: Input) -> Output:
    return Output(message=f"Preview: {input.name}!")
"""

PREVIEW_GREET_SOURCE_2 = """\
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    name: str

class Output(SkillOutput):
    message: str

async def handle(input: Input) -> Output:
    return Output(message=f"Preview2: {input.name}!")
"""


@pytest.fixture
def backend():
    return TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
    )


@pytest.fixture
def tenant_app(backend):
    return HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=backend)


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
# Preview status
# ---------------------------------------------------------------------------

async def test_preview_endpoint_returns_preview_status(client):
    r1 = await client.post(
        "/tenants/prev-user/skills/greet/customize",
        json={"source_code": PREVIEW_GREET_SOURCE},
    )
    assert r1.status_code == 200
    vid = r1.json()["variant_id"]

    r2 = await client.post(f"/tenants/prev-user/skills/greet/variants/{vid}/preview")
    assert r2.status_code == 200
    assert r2.json()["status"] == "preview"


async def test_preview_routes_tenant_calls(client):
    r1 = await client.post(
        "/tenants/prev-route/skills/greet/customize",
        json={"source_code": PREVIEW_GREET_SOURCE},
    )
    vid = r1.json()["variant_id"]
    await client.post(f"/tenants/prev-route/skills/greet/variants/{vid}/preview")

    r = await _post_skill(client, "greet", {"name": "Alice"}, tenant_id="prev-route")
    assert r.status_code == 200
    assert r.json()["message"] == "Preview: Alice!"


async def test_preview_does_not_displace_promoted(client):
    r1 = await client.post(
        "/tenants/prev-coexist/skills/greet/customize",
        json={"source_code": CUSTOM_GREET_SOURCE, "auto_promote": True},
    )
    promoted_id = r1.json()["variant_id"]

    r2 = await client.post(
        "/tenants/prev-coexist/skills/greet/customize",
        json={"source_code": PREVIEW_GREET_SOURCE},
    )
    preview_id = r2.json()["variant_id"]
    await client.post(f"/tenants/prev-coexist/skills/greet/variants/{preview_id}/preview")

    r = await _post_skill(client, "greet", {"name": "Bob"}, tenant_id="prev-coexist")
    assert "Preview" in r.json()["message"]

    r_list = await client.get("/tenants/prev-coexist/skills/greet/variants")
    statuses = {v["variant_id"]: v["status"] for v in r_list.json()}
    assert statuses[promoted_id] == "promoted"
    assert statuses[preview_id] == "preview"


async def test_second_preview_displaces_first(client):
    r1 = await client.post(
        "/tenants/prev-displace/skills/greet/customize",
        json={"source_code": PREVIEW_GREET_SOURCE},
    )
    vid1 = r1.json()["variant_id"]
    await client.post(f"/tenants/prev-displace/skills/greet/variants/{vid1}/preview")

    r2 = await client.post(
        "/tenants/prev-displace/skills/greet/customize",
        json={"source_code": PREVIEW_GREET_SOURCE_2},
    )
    vid2 = r2.json()["variant_id"]
    await client.post(f"/tenants/prev-displace/skills/greet/variants/{vid2}/preview")

    r = await _post_skill(client, "greet", {"name": "Carl"}, tenant_id="prev-displace")
    assert r.json()["message"] == "Preview2: Carl!"

    r_list = await client.get("/tenants/prev-displace/skills/greet/variants")
    statuses = {v["variant_id"]: v["status"] for v in r_list.json()}
    assert statuses[vid2] == "preview"
    assert vid1 in statuses


async def test_preview_storage_persisted(tmp_path):
    from harnessapi.multitenancy import SQLiteStorageBackend
    from harnessapi.app import _load_tenant_variants

    storage = SQLiteStorageBackend(path=tmp_path / "prev.db")
    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=storage,
    )
    app = HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=backend)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.post(
            "/tenants/persist-prev/skills/greet/customize",
            json={"source_code": PREVIEW_GREET_SOURCE},
        )
        vid = r1.json()["variant_id"]
        await c.post(f"/tenants/persist-prev/skills/greet/variants/{vid}/preview")

    storage2 = SQLiteStorageBackend(path=tmp_path / "prev.db")
    backend2 = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=storage2,
    )
    base_skills = {name: s for name, s in app.skills.items()}
    await _load_tenant_variants(backend2, base_skills)

    preview = backend2.registry.get_preview("persist-prev", "greet")
    assert preview is not None
    assert preview.status == "preview"
