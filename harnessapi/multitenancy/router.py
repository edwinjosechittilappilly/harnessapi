from __future__ import annotations

import asyncio
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .models import SkillVariant, VariantResponse, VariantSummary
from .sandbox import validate_handler_source, compile_variant_handler

if TYPE_CHECKING:
    from ..skill import Skill
    from .backend import TenantBackend


def build_tenant_router(backend: TenantBackend, base_skills: dict[str, Skill]) -> APIRouter:
    router = APIRouter(prefix="/tenants", tags=["tenants"])

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _get_base_skill(skill_name: str) -> Skill:
        skill = base_skills.get(skill_name)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Base skill '{skill_name}' not found")
        return skill

    def _get_variant_any(variant_id: str) -> SkillVariant:
        variant = backend.registry.get_variant(variant_id)
        if variant is None:
            raise HTTPException(status_code=404, detail=f"Variant '{variant_id}' not found")
        return variant

    def _validate_and_compile(skill_name: str, source_code: str) -> Any:
        violations = validate_handler_source(source_code, backend.sandbox_import_blocklist)
        if violations:
            raise HTTPException(
                status_code=422,
                detail={"message": "Handler source failed validation", "violations": violations},
            )
        try:
            return compile_variant_handler(source_code, skill_name, str(uuid.uuid4()))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _count_all_variants(tenant_id: str, skill_name: str) -> int:
        all_v = backend.registry.list_all_for_tenant(tenant_id)
        return sum(1 for v in all_v if v.base_skill_name == skill_name)

    # ------------------------------------------------------------------
    # Clone — returns base handler source as starting point for agent
    # ------------------------------------------------------------------

    @router.post("/{tenant_id}/skills/{skill_name}/clone")
    async def clone_skill(tenant_id: str, skill_name: str):
        skill = _get_base_skill(skill_name)

        if _count_all_variants(tenant_id, skill_name) >= backend.max_variants_per_tenant_per_skill:
            raise HTTPException(
                status_code=409,
                detail=f"Max variants ({backend.max_variants_per_tenant_per_skill}) reached for this skill",
            )

        # Read base handler source from disk if available
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
            handler=skill.handler,  # points at base handler until customised
            status="sandbox",
            created_at=datetime.now(timezone.utc),
            input_model=skill.input_model,
            output_model=skill.output_model,
        )
        backend.registry.add_sandbox(variant)
        await backend.storage.save_variant(variant)

        resp = VariantResponse(
            variant_id=variant_id,
            tenant_id=tenant_id,
            base_skill_name=skill_name,
            status="sandbox",
            source_code=source_code,
        )
        return JSONResponse(content=resp.model_dump())

    # ------------------------------------------------------------------
    # Customize — validate + compile source, create/update sandbox variant
    # ------------------------------------------------------------------

    @router.post("/{tenant_id}/skills/{skill_name}/customize")
    async def customize_skill(tenant_id: str, skill_name: str, body: dict):
        source_code: str = body.get("source_code", "")
        if not source_code.strip():
            raise HTTPException(status_code=422, detail="source_code is required")

        skill = _get_base_skill(skill_name)

        if _count_all_variants(tenant_id, skill_name) >= backend.max_variants_per_tenant_per_skill:
            raise HTTPException(
                status_code=409,
                detail=f"Max variants ({backend.max_variants_per_tenant_per_skill}) reached",
            )

        auto_promote: bool = body.get("auto_promote", backend.auto_promote)
        meta_overrides: dict = body.get("meta_overrides", {})

        handler = _validate_and_compile(skill_name, source_code)
        variant_id = str(uuid.uuid4())
        status = "promoted" if auto_promote else "sandbox"

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
            meta_overrides=meta_overrides,
        )

        if auto_promote:
            previous = backend.registry.set_promoted(variant)
            if previous is not None:
                await backend.storage.demote_variant(previous.variant_id)
        else:
            backend.registry.add_sandbox(variant)

        await backend.storage.save_variant(variant)

        return JSONResponse(content=VariantResponse(
            variant_id=variant_id,
            tenant_id=tenant_id,
            base_skill_name=skill_name,
            status=status,
        ).model_dump())

    # ------------------------------------------------------------------
    # Promote
    # ------------------------------------------------------------------

    @router.post("/{tenant_id}/skills/{skill_name}/variants/{variant_id}/promote")
    async def promote_variant(tenant_id: str, skill_name: str, variant_id: str):
        _get_base_skill(skill_name)
        variant = _get_variant_any(variant_id)
        if variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
            raise HTTPException(status_code=404, detail="Variant not found")

        previous = backend.registry.set_promoted(variant)
        if previous is not None and previous.variant_id != variant_id:
            await backend.storage.demote_variant(previous.variant_id)

        variant.status = "promoted"
        await backend.storage.promote_variant(variant_id)

        return JSONResponse(content=VariantResponse(
            variant_id=variant_id, tenant_id=tenant_id,
            base_skill_name=skill_name, status="promoted",
        ).model_dump())

    # ------------------------------------------------------------------
    # Demote
    # ------------------------------------------------------------------

    @router.post("/{tenant_id}/skills/{skill_name}/variants/{variant_id}/demote")
    async def demote_variant(tenant_id: str, skill_name: str, variant_id: str):
        _get_base_skill(skill_name)
        variant = _get_variant_any(variant_id)
        if variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
            raise HTTPException(status_code=404, detail="Variant not found")

        backend.registry.demote(variant)
        variant.status = "sandbox"
        await backend.storage.demote_variant(variant_id)

        return JSONResponse(content=VariantResponse(
            variant_id=variant_id, tenant_id=tenant_id,
            base_skill_name=skill_name, status="sandbox",
        ).model_dump())

    # ------------------------------------------------------------------
    # Run (sandbox test execution)
    # ------------------------------------------------------------------

    @router.post("/{tenant_id}/skills/{skill_name}/variants/{variant_id}/run")
    async def run_variant(tenant_id: str, skill_name: str, variant_id: str, body: dict):
        _get_base_skill(skill_name)
        variant = _get_variant_any(variant_id)
        if variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
            raise HTTPException(status_code=404, detail="Variant not found")

        try:
            input_obj = variant.input_model.model_validate(body)
        except ValidationError as exc:
            return JSONResponse(status_code=422, content={"detail": exc.errors()})

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
                status_code=200,
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
        _get_base_skill(skill_name)
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

    return router
