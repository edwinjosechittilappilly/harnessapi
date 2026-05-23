"""Integration tests — storage backends (SQLite, InProcess, LocalFile) and sandbox state."""
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


@pytest.fixture
def backend():
    return TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=InProcessStorageBackend(),
    )


# ---------------------------------------------------------------------------
# 14. SQLite storage
# ---------------------------------------------------------------------------

async def test_sqlite_storage_saves_and_loads_promoted_variant(tmp_path):
    from harnessapi.multitenancy import SQLiteStorageBackend
    from harnessapi.multitenancy.models import SkillVariant
    from harnessapi.multitenancy.sandbox import compile_variant_handler
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
    promoted = await backend.storage.load_promoted_variants()
    assert promoted == []


# ---------------------------------------------------------------------------
# 15. LocalFileStorageBackend
# ---------------------------------------------------------------------------

async def test_local_file_storage_save_and_load(tmp_path):
    from harnessapi.multitenancy import LocalFileStorageBackend

    storage = LocalFileStorageBackend(variants_dir=tmp_path / "variants")
    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=storage,
    )
    app = HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=backend)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.post(
            "/tenants/file-user/skills/greet/customize",
            json={"source_code": CUSTOM_GREET_SOURCE},
        )
        vid = r1.json()["variant_id"]
        await c.post(f"/tenants/file-user/skills/greet/variants/{vid}/promote")

    assert (tmp_path / "variants" / f"{vid}.json").exists()

    storage2 = LocalFileStorageBackend(variants_dir=tmp_path / "variants")
    partials = await storage2.load_promoted_variants()
    assert any(p.variant_id == vid for p in partials)
    assert all(p.status == "promoted" for p in partials)


async def test_local_file_storage_delete(tmp_path):
    from harnessapi.multitenancy import LocalFileStorageBackend

    storage = LocalFileStorageBackend(variants_dir=tmp_path / "variants")
    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=storage,
    )
    app = HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=backend)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.post(
            "/tenants/del-user/skills/greet/customize",
            json={"source_code": CUSTOM_GREET_SOURCE},
        )
        vid = r1.json()["variant_id"]
        await c.delete(f"/tenants/del-user/skills/greet/variants/{vid}")

    assert not (tmp_path / "variants" / f"{vid}.json").exists()


async def test_local_file_storage_list_variants(tmp_path):
    from harnessapi.multitenancy import LocalFileStorageBackend

    storage = LocalFileStorageBackend(variants_dir=tmp_path / "variants")
    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=storage,
    )
    app = HarnessAPI(skills_dir=SKILLS_DIR, tenant_backend=backend)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/tenants/list-user/skills/greet/customize", json={"source_code": CUSTOM_GREET_SOURCE})
        await c.post("/tenants/other-user/skills/greet/customize", json={"source_code": CUSTOM_GREET_SOURCE})

    variants = await storage.list_variants("list-user")
    assert len(variants) == 1
    assert variants[0].tenant_id == "list-user"


# ---------------------------------------------------------------------------
# 16. Sandbox provider caching
# ---------------------------------------------------------------------------

def test_sandbox_provider_is_cached():
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
# 17. Stale sandbox connections dropped on restore
# ---------------------------------------------------------------------------

async def test_restore_sandbox_connections_drops_unreachable(tmp_path):
    from harnessapi.multitenancy import SQLiteStorageBackend, SandboxRegistry
    from harnessapi.multitenancy.sandbox_registry import SandboxConnection

    storage = SQLiteStorageBackend(path=tmp_path / "sb.db")
    registry = SandboxRegistry()
    backend = TenantBackend(
        tenant_extractor=lambda req: req.headers.get("X-Tenant-ID"),
        storage=storage,
        sandbox_registry=registry,
    )

    stale = SandboxConnection(
        tenant_id="stale-tenant",
        endpoint_url="http://127.0.0.1:1",
        sandbox_type="local_subprocess",
        created_at=datetime.now(timezone.utc),
    )
    await storage.save_sandbox(stale)

    from harnessapi.app import _restore_sandbox_connections
    await _restore_sandbox_connections(backend)

    assert registry.get("stale-tenant") is None

    remaining = await storage.load_sandboxes()
    assert not any(r["tenant_id"] == "stale-tenant" for r in remaining)
