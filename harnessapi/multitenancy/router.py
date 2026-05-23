from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .models import VariantSummary
from .ops import VariantOpsError, op_clone, op_customize, op_demote, op_promote

if TYPE_CHECKING:
    from ..skill import Skill
    from .backend import TenantBackend


def build_tenant_router(backend: TenantBackend, base_skills: dict[str, Skill]) -> APIRouter:
    router = APIRouter(prefix="/tenants", tags=["tenants"])

    def _ops_error_to_http(exc: VariantOpsError) -> HTTPException:
        return HTTPException(status_code=exc.status, detail=str(exc))

    # ------------------------------------------------------------------
    # Clone
    # ------------------------------------------------------------------

    @router.post("/{tenant_id}/skills/{skill_name}/clone")
    async def clone_skill(tenant_id: str, skill_name: str):
        try:
            resp = await op_clone(backend, base_skills, tenant_id, skill_name)
        except VariantOpsError as exc:
            raise _ops_error_to_http(exc)
        return JSONResponse(content=resp.model_dump())

    # ------------------------------------------------------------------
    # Customize
    # ------------------------------------------------------------------

    @router.post("/{tenant_id}/skills/{skill_name}/customize")
    async def customize_skill(tenant_id: str, skill_name: str, body: dict):
        try:
            resp = await op_customize(
                backend,
                base_skills,
                tenant_id,
                skill_name,
                source_code=body.get("source_code", ""),
                auto_promote=body.get("auto_promote", backend.auto_promote),
                meta_overrides=body.get("meta_overrides", {}),
            )
        except VariantOpsError as exc:
            raise _ops_error_to_http(exc)
        return JSONResponse(content=resp.model_dump())

    # ------------------------------------------------------------------
    # Promote
    # ------------------------------------------------------------------

    @router.post("/{tenant_id}/skills/{skill_name}/variants/{variant_id}/promote")
    async def promote_variant(tenant_id: str, skill_name: str, variant_id: str):
        try:
            resp = await op_promote(backend, base_skills, tenant_id, skill_name, variant_id)
        except VariantOpsError as exc:
            raise _ops_error_to_http(exc)
        return JSONResponse(content=resp.model_dump())

    # ------------------------------------------------------------------
    # Demote
    # ------------------------------------------------------------------

    @router.post("/{tenant_id}/skills/{skill_name}/variants/{variant_id}/demote")
    async def demote_variant(tenant_id: str, skill_name: str, variant_id: str):
        try:
            resp = await op_demote(backend, base_skills, tenant_id, skill_name, variant_id)
        except VariantOpsError as exc:
            raise _ops_error_to_http(exc)
        return JSONResponse(content=resp.model_dump())

    # ------------------------------------------------------------------
    # Run (sandbox test execution)
    # ------------------------------------------------------------------

    @router.post("/{tenant_id}/skills/{skill_name}/variants/{variant_id}/run")
    async def run_variant(tenant_id: str, skill_name: str, variant_id: str, body: dict):
        if base_skills.get(skill_name) is None:
            raise HTTPException(status_code=404, detail=f"Base skill '{skill_name}' not found")

        variant = backend.registry.get_variant(variant_id)
        if variant is None or variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
            raise HTTPException(status_code=404, detail="Variant not found")

        try:
            input_obj = variant.input_model.model_validate(body)
        except ValidationError as exc:
            return JSONResponse(status_code=422, content={"detail": exc.errors()})

        # Forward to sandbox if provisioned — use validated input so error provenance is consistent
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
                    return JSONResponse(content=result)
                except Exception as exc:
                    return JSONResponse(
                        status_code=502,
                        content={"error": f"Sandbox error: {exc}", "traceback": traceback.format_exc()},
                    )

        # In-process fallback
        try:
            timeout = backend.sandbox_run_timeout_secs
            if variant.is_streaming_handler():
                chunks: list[str] = []
                async def _collect():
                    async for chunk in variant.handler(input_obj):
                        chunks.append(str(chunk))
                await asyncio.wait_for(_collect(), timeout=timeout)
                return JSONResponse(content={"chunks": chunks})
            else:
                result = await asyncio.wait_for(variant.handler(input_obj), timeout=timeout)
                return JSONResponse(content=result.model_dump())
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=408,
                content={"error": f"Variant timed out after {timeout}s"},
            )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={"error": str(exc), "traceback": traceback.format_exc()},
            )

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    @router.delete("/{tenant_id}/skills/{skill_name}/variants/{variant_id}")
    async def delete_variant(tenant_id: str, skill_name: str, variant_id: str):
        variant = backend.registry.get_variant(variant_id)
        if variant is None or variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
            raise HTTPException(status_code=404, detail="Variant not found")

        backend.registry.remove_variant(variant_id)
        await backend.storage.delete_variant(variant_id)
        return JSONResponse(content={"deleted": variant_id})

    # ------------------------------------------------------------------
    # List skills for tenant
    # ------------------------------------------------------------------

    @router.get("/{tenant_id}/skills")
    async def list_tenant_skills(tenant_id: str):
        variants = backend.registry.list_all_for_tenant(tenant_id)
        return JSONResponse(content=[VariantSummary(v).model_dump() for v in variants])

    # ------------------------------------------------------------------
    # List variants for a specific skill
    # ------------------------------------------------------------------

    @router.get("/{tenant_id}/skills/{skill_name}/variants")
    async def list_skill_variants(tenant_id: str, skill_name: str):
        if base_skills.get(skill_name) is None:
            raise HTTPException(status_code=404, detail=f"Base skill '{skill_name}' not found")
        variants = [
            v for v in backend.registry.list_all_for_tenant(tenant_id)
            if v.base_skill_name == skill_name
        ]
        return JSONResponse(content=[VariantSummary(v).model_dump() for v in variants])

    # ------------------------------------------------------------------
    # Get source
    # ------------------------------------------------------------------

    @router.get("/{tenant_id}/skills/{skill_name}/variants/{variant_id}/source")
    async def get_variant_source(tenant_id: str, skill_name: str, variant_id: str):
        variant = backend.registry.get_variant(variant_id)
        if variant is None or variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
            raise HTTPException(status_code=404, detail="Variant not found")
        return JSONResponse(content={"source_code": variant.handler_source})

    # ------------------------------------------------------------------
    # Sandbox lifecycle endpoints (only registered when sandbox_registry set)
    # ------------------------------------------------------------------

    if backend.sandbox_registry is not None:
        _sb_registry = backend.sandbox_registry

        def _get_provider():
            p = backend.get_sandbox_provider()
            if p is None:
                raise HTTPException(
                    status_code=400,
                    detail="No sandbox_provider configured on TenantBackend"
                )
            return p

        @router.post("/{tenant_id}/sandbox/provision")
        async def provision_sandbox(tenant_id: str, body: dict | None = None):
            body = body or {}
            existing = _sb_registry.get(tenant_id)
            if existing is not None:
                return JSONResponse(content={
                    "tenant_id": tenant_id,
                    "endpoint_url": existing.endpoint_url,
                    "sandbox_type": existing.sandbox_type,
                    "status": "already_running",
                })
            provider = _get_provider()
            skills_dir = body.get("skills_dir", "")
            conn = await provider.provision(tenant_id, skills_dir)
            _sb_registry.register(conn)
            if hasattr(backend.storage, "save_sandbox"):
                await backend.storage.save_sandbox(conn)
            return JSONResponse(content={
                "tenant_id": tenant_id,
                "endpoint_url": conn.endpoint_url,
                "sandbox_type": conn.sandbox_type,
                "pid": conn.pid,
                "status": "running",
            })

        @router.delete("/{tenant_id}/sandbox")
        async def teardown_sandbox(tenant_id: str):
            conn = _sb_registry.get(tenant_id)
            if conn is None:
                raise HTTPException(status_code=404, detail=f"No sandbox for tenant {tenant_id!r}")
            provider = _get_provider()
            await provider.teardown(conn)
            _sb_registry.deregister(tenant_id)
            if hasattr(backend.storage, "delete_sandbox"):
                await backend.storage.delete_sandbox(tenant_id)
            return JSONResponse(content={"status": "torn_down", "tenant_id": tenant_id})

        @router.get("/{tenant_id}/sandbox/health")
        async def sandbox_health(tenant_id: str):
            conn = _sb_registry.get(tenant_id)
            if conn is None:
                return JSONResponse(content={"status": "not_provisioned", "tenant_id": tenant_id})
            from .sandbox_client import sandbox_client as _sc
            healthy = await _sc.health_check(conn)
            return JSONResponse(content={
                "status": "healthy" if healthy else "unreachable",
                "tenant_id": tenant_id,
                "endpoint_url": conn.endpoint_url,
                "last_seen": conn.last_seen.isoformat() if conn.last_seen else None,
            })

        @router.post("/{tenant_id}/skills/{skill_name}/push-to-sandbox")
        async def push_to_sandbox(tenant_id: str, skill_name: str):
            if base_skills.get(skill_name) is None:
                raise HTTPException(status_code=404, detail=f"Base skill '{skill_name}' not found")
            conn = _sb_registry.get(tenant_id)
            if conn is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No sandbox registered for tenant {tenant_id!r}. Call /provision first.",
                )
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
            return JSONResponse(content={
                "status": "pushed",
                "skill_name": skill_name,
                "tenant_id": tenant_id,
                "endpoint_url": conn.endpoint_url,
            })

    return router
