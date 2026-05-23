from __future__ import annotations

import asyncio
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from fastmcp import FastMCP
from pydantic import ValidationError

from .models import SkillVariant, VariantResponse, VariantSummary
from .sandbox import validate_handler_source, compile_variant_handler

if TYPE_CHECKING:
    from ..skill import Skill
    from .backend import TenantBackend


def build_admin_mcp_server(
    backend: TenantBackend,
    base_skills: dict[str, Skill],
    server_name: str = "HarnessAPI Admin",
) -> FastMCP:
    """Build an MCP server exposing tenant management endpoints as tools."""
    mcp = FastMCP(server_name)

    # ------------------------------------------------------------------
    # Shared helpers (mirrors router.py logic without HTTP layer)
    # ------------------------------------------------------------------

    def _get_base_skill(skill_name: str) -> Skill:
        skill = base_skills.get(skill_name)
        if skill is None:
            raise ValueError(f"Base skill '{skill_name}' not found")
        return skill

    def _get_variant(variant_id: str) -> SkillVariant:
        variant = backend.registry.get_variant(variant_id)
        if variant is None:
            raise ValueError(f"Variant '{variant_id}' not found")
        return variant

    def _validate_and_compile(skill_name: str, source_code: str) -> Any:
        violations = validate_handler_source(source_code, backend.sandbox_import_blocklist)
        if violations:
            raise ValueError(f"Handler source failed validation: {violations}")
        try:
            return compile_variant_handler(source_code, skill_name, str(uuid.uuid4()))
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    def _count_variants(tenant_id: str, skill_name: str) -> int:
        return sum(
            1 for v in backend.registry.list_all_for_tenant(tenant_id)
            if v.base_skill_name == skill_name
        )

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def clone_skill(tenant_id: str, skill_name: str) -> dict:
        """Copy a base skill's handler source as a starting point for customization."""
        skill = _get_base_skill(skill_name)
        if _count_variants(tenant_id, skill_name) >= backend.max_variants_per_tenant_per_skill:
            raise ValueError(f"Max variants ({backend.max_variants_per_tenant_per_skill}) reached for this skill")

        source_code = ""
        if skill.folder is not None:
            handler_file = skill.folder / "handler.py"
            if handler_file.exists():
                source_code = handler_file.read_text()

        variant_id = str(uuid.uuid4())
        variant = SkillVariant(
            variant_id=variant_id,
            tenant_id=tenant_id,
            base_skill_name=skill_name,
            handler_source=source_code,
            handler=skill.handler,
            status="sandbox",
            created_at=datetime.now(timezone.utc),
            input_model=skill.input_model,
            output_model=skill.output_model,
        )
        backend.registry.add_sandbox(variant)
        await backend.storage.save_variant(variant)

        return VariantResponse(
            variant_id=variant_id,
            tenant_id=tenant_id,
            base_skill_name=skill_name,
            status="sandbox",
            source_code=source_code,
        ).model_dump()

    @mcp.tool()
    async def customize_skill(
        tenant_id: str,
        skill_name: str,
        source_code: str,
        auto_promote: bool = False,
        meta_overrides: dict | None = None,
    ) -> dict:
        """Submit modified handler source for a skill. Validates and stores the variant."""
        if not source_code.strip():
            raise ValueError("source_code is required")

        skill = _get_base_skill(skill_name)
        if _count_variants(tenant_id, skill_name) >= backend.max_variants_per_tenant_per_skill:
            raise ValueError(f"Max variants ({backend.max_variants_per_tenant_per_skill}) reached")

        effective_auto_promote = auto_promote or backend.auto_promote
        overrides = meta_overrides or {}

        handler = _validate_and_compile(skill_name, source_code)
        variant_id = str(uuid.uuid4())
        status = "promoted" if effective_auto_promote else "sandbox"

        variant = SkillVariant(
            variant_id=variant_id,
            tenant_id=tenant_id,
            base_skill_name=skill_name,
            handler_source=source_code,
            handler=handler,
            status=status,
            created_at=datetime.now(timezone.utc),
            input_model=skill.input_model,
            output_model=skill.output_model,
            meta_overrides=overrides,
        )

        if effective_auto_promote:
            previous = backend.registry.set_promoted(variant)
            if previous is not None:
                await backend.storage.demote_variant(previous.variant_id)
        else:
            backend.registry.add_sandbox(variant)

        await backend.storage.save_variant(variant)

        return VariantResponse(
            variant_id=variant_id,
            tenant_id=tenant_id,
            base_skill_name=skill_name,
            status=status,
        ).model_dump()

    @mcp.tool()
    async def promote_variant(tenant_id: str, skill_name: str, variant_id: str) -> dict:
        """Make a sandbox variant the active handler for a tenant's skill."""
        _get_base_skill(skill_name)
        variant = _get_variant(variant_id)
        if variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
            raise ValueError("Variant not found for this tenant/skill")

        previous = backend.registry.set_promoted(variant)
        if previous is not None and previous.variant_id != variant_id:
            await backend.storage.demote_variant(previous.variant_id)

        variant.status = "promoted"
        await backend.storage.promote_variant(variant_id)

        return VariantResponse(
            variant_id=variant_id,
            tenant_id=tenant_id,
            base_skill_name=skill_name,
            status="promoted",
        ).model_dump()

    @mcp.tool()
    async def demote_variant(tenant_id: str, skill_name: str, variant_id: str) -> dict:
        """Move a promoted variant back to sandbox status."""
        _get_base_skill(skill_name)
        variant = _get_variant(variant_id)
        if variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
            raise ValueError("Variant not found for this tenant/skill")

        backend.registry.demote(variant)
        variant.status = "sandbox"
        await backend.storage.demote_variant(variant_id)

        return VariantResponse(
            variant_id=variant_id,
            tenant_id=tenant_id,
            base_skill_name=skill_name,
            status="sandbox",
        ).model_dump()

    @mcp.tool()
    async def run_variant(
        tenant_id: str,
        skill_name: str,
        variant_id: str,
        input_data: dict,
    ) -> dict:
        """Test a variant with input. Forwards to sandbox if provisioned, otherwise runs in-process."""
        _get_base_skill(skill_name)
        variant = _get_variant(variant_id)
        if variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
            raise ValueError("Variant not found for this tenant/skill")

        try:
            input_obj = variant.input_model.model_validate(input_data)
        except ValidationError as exc:
            return {"error": "validation_error", "detail": exc.errors()}

        # Forward to sandbox if provisioned
        if backend.sandbox_registry is not None:
            conn = backend.sandbox_registry.get(tenant_id)
            if conn is not None:
                from .sandbox_client import sandbox_client as _sc
                try:
                    await _sc.push_skill(conn, skill_name, variant.handler_source)
                    result = await _sc.forward(conn, skill_name, input_data, timeout=backend.sandbox_run_timeout_secs)
                    return result
                except Exception as exc:
                    return {"error": str(exc), "traceback": traceback.format_exc()}

        # In-process fallback
        try:
            timeout = backend.sandbox_run_timeout_secs
            if variant.is_streaming_handler():
                chunks: list[str] = []
                async def _collect():
                    async for chunk in variant.handler(input_obj):
                        chunks.append(str(chunk))
                await asyncio.wait_for(_collect(), timeout=timeout)
                return {"chunks": chunks}
            else:
                result = await asyncio.wait_for(variant.handler(input_obj), timeout=timeout)
                return result.model_dump()
        except asyncio.TimeoutError:
            return {"error": f"Variant timed out after {timeout}s"}
        except Exception as exc:
            return {"error": str(exc), "traceback": traceback.format_exc()}

    @mcp.tool()
    async def get_variant_source(tenant_id: str, skill_name: str, variant_id: str) -> dict:
        """Get the handler source code for a variant."""
        variant = backend.registry.get_variant(variant_id)
        if variant is None or variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
            raise ValueError("Variant not found")
        return {"source_code": variant.handler_source}

    @mcp.tool()
    async def list_tenant_skills(tenant_id: str) -> list:
        """List all skill variants (sandbox + promoted) for a tenant."""
        variants = backend.registry.list_all_for_tenant(tenant_id)
        return [VariantSummary(v).model_dump() for v in variants]

    @mcp.tool()
    async def provision_sandbox(tenant_id: str, skills_dir: str = "") -> dict:
        """Provision a sandbox for a tenant. Returns the sandbox endpoint URL."""
        if backend.sandbox_registry is None:
            raise ValueError("sandbox_registry is not configured on TenantBackend")
        provider = backend.get_sandbox_provider()
        if provider is None:
            raise ValueError("No sandbox_provider configured on TenantBackend")

        existing = backend.sandbox_registry.get(tenant_id)
        if existing is not None:
            return {
                "tenant_id": tenant_id,
                "endpoint_url": existing.endpoint_url,
                "sandbox_type": existing.sandbox_type,
                "status": "already_running",
            }

        conn = await provider.provision(tenant_id, skills_dir)
        backend.sandbox_registry.register(conn)
        if hasattr(backend.storage, "save_sandbox"):
            await backend.storage.save_sandbox(conn)

        return {
            "tenant_id": tenant_id,
            "endpoint_url": conn.endpoint_url,
            "sandbox_type": conn.sandbox_type,
            "pid": conn.pid,
            "status": "running",
        }

    @mcp.tool()
    async def teardown_sandbox(tenant_id: str) -> dict:
        """Tear down a tenant's sandbox."""
        if backend.sandbox_registry is None:
            raise ValueError("sandbox_registry is not configured on TenantBackend")
        conn = backend.sandbox_registry.get(tenant_id)
        if conn is None:
            raise ValueError(f"No sandbox for tenant {tenant_id!r}")
        provider = backend.get_sandbox_provider()
        if provider is None:
            raise ValueError("No sandbox_provider configured on TenantBackend")

        await provider.teardown(conn)
        backend.sandbox_registry.deregister(tenant_id)
        if hasattr(backend.storage, "delete_sandbox"):
            await backend.storage.delete_sandbox(tenant_id)

        return {"status": "torn_down", "tenant_id": tenant_id}

    @mcp.tool()
    async def sandbox_health(tenant_id: str) -> dict:
        """Check the health of a tenant's sandbox."""
        if backend.sandbox_registry is None:
            raise ValueError("sandbox_registry is not configured on TenantBackend")
        conn = backend.sandbox_registry.get(tenant_id)
        if conn is None:
            return {"status": "not_provisioned", "tenant_id": tenant_id}

        from .sandbox_client import sandbox_client as _sc
        healthy = await _sc.health_check(conn)
        return {
            "status": "healthy" if healthy else "unreachable",
            "tenant_id": tenant_id,
            "endpoint_url": conn.endpoint_url,
            "last_seen": conn.last_seen.isoformat() if conn.last_seen else None,
        }

    @mcp.tool()
    async def push_to_sandbox(tenant_id: str, skill_name: str) -> dict:
        """Push a promoted variant's handler source to the tenant's sandbox."""
        _get_base_skill(skill_name)
        if backend.sandbox_registry is None:
            raise ValueError("sandbox_registry is not configured on TenantBackend")
        conn = backend.sandbox_registry.get(tenant_id)
        if conn is None:
            raise ValueError(f"No sandbox registered for tenant {tenant_id!r}. Call provision_sandbox first.")

        variant = backend.registry.get_promoted(tenant_id, skill_name)
        if variant is not None:
            source = variant.handler_source
        else:
            base = base_skills.get(skill_name)
            source = ""
            if base and base.folder:
                hp = base.folder / "handler.py"
                if hp.exists():
                    source = hp.read_text()

        from .sandbox_client import sandbox_client as _sc
        await _sc.push_skill(conn, skill_name, source)
        return {
            "status": "pushed",
            "skill_name": skill_name,
            "tenant_id": tenant_id,
            "endpoint_url": conn.endpoint_url,
        }

    return mcp
