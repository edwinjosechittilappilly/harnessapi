"""Integration tests — list variants, get source, max variants, streaming."""
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

STREAMING_GREET_SOURCE = """\
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    name: str

async def handle(input: Input):
    yield f"Hey"
    yield f"{input.name}!"
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
# 12. Max variants per tenant per skill
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

        r = await c.post(
            "/tenants/user-max/skills/greet/customize",
            json={"source_code": CUSTOM_GREET_SOURCE},
        )
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# 13. Streaming variant
# ---------------------------------------------------------------------------

async def test_streaming_variant_sse(client):
    r1 = await client.post(
        "/tenants/user-sse/skills/greet/customize",
        json={"source_code": STREAMING_GREET_SOURCE, "auto_promote": True},
    )
    assert r1.json()["status"] == "promoted"

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
