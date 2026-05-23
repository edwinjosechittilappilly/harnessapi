from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from pydantic import ValidationError

from .models import VariantSummary
from .ops import VariantOpsError, op_clone, op_customize, op_demote, op_promote

if TYPE_CHECKING:
    from ..skill import Skill
    from .backend import TenantBackend


def build_admin_mcp_server(
    backend: TenantBackend,
    base_skills: dict[str, Skill],
    server_name: str = "HarnessAPI Admin",
) -> FastMCP:
    """Build an MCP server exposing tenant management endpoints as tools.

    WARNING: This server has no built-in authentication. Every tool can execute
    arbitrary validated code on the server. Only enable with auth middleware in
    production (enable_admin_mcp=True with appropriate middleware protecting /admin-mcp).
    """
    mcp = FastMCP(server_name)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def clone_skill(tenant_id: str, skill_name: str) -> dict:
        """Copy a base skill's handler source as a starting point for customization."""
        try:
            resp = await op_clone(backend, base_skills, tenant_id, skill_name)
        except VariantOpsError as exc:
            raise ValueError(str(exc)) from exc
        return resp.model_dump()

    @mcp.tool()
    async def customize_skill(
        tenant_id: str,
        skill_name: str,
        source_code: str,
        auto_promote: bool = False,
        meta_overrides: dict | None = None,
    ) -> dict:
        """Submit modified handler source for a skill. Validates and stores the variant."""
        try:
            resp = await op_customize(
                backend, base_skills, tenant_id, skill_name,
                source_code=source_code,
                auto_promote=auto_promote,
                meta_overrides=meta_overrides,
            )
        except VariantOpsError as exc:
            raise ValueError(str(exc)) from exc
        return resp.model_dump()

    @mcp.tool()
    async def promote_variant(tenant_id: str, skill_name: str, variant_id: str) -> dict:
        """Make a sandbox variant the active handler for a tenant's skill."""
        try:
            resp = await op_promote(backend, base_skills, tenant_id, skill_name, variant_id)
        except VariantOpsError as exc:
            raise ValueError(str(exc)) from exc
        return resp.model_dump()

    @mcp.tool()
    async def demote_variant(tenant_id: str, skill_name: str, variant_id: str) -> dict:
        """Move a promoted variant back to sandbox status."""
        try:
            resp = await op_demote(backend, base_skills, tenant_id, skill_name, variant_id)
        except VariantOpsError as exc:
            raise ValueError(str(exc)) from exc
        return resp.model_dump()

    @mcp.tool()
    async def run_variant(
        tenant_id: str,
        skill_name: str,
        variant_id: str,
        input_data: dict,
    ) -> dict:
        """Test a variant with input. Forwards to sandbox if provisioned, otherwise runs in-process."""
        if base_skills.get(skill_name) is None:
            raise ValueError(f"Base skill '{skill_name}' not found")

        variant = backend.registry.get_variant(variant_id)
        if variant is None or variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
            raise ValueError("Variant not found")

        try:
            input_obj = variant.input_model.model_validate(input_data)
        except ValidationError as exc:
            return {"error": "validation_error", "detail": exc.errors()}

        # Forward to sandbox if provisioned — use validated input for consistent error provenance
        if backend.sandbox_registry is not None:
            conn = backend.sandbox_registry.get(tenant_id)
            if conn is not None:
                from .sandbox_client import sandbox_client as _sc
                try:
                    await _sc.push_skill(conn, skill_name, variant.handler_source)
                    result = await _sc.forward(
                        conn, skill_name,
                        input_obj.model_dump(),
                        timeout=backend.sandbox_run_timeout_secs,
                    )
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
        if base_skills.get(skill_name) is None:
            raise ValueError(f"Base skill '{skill_name}' not found")
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
