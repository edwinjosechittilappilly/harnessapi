"""Shared business-logic operations used by both the HTTP router and the admin MCP server.

Keeping these here ensures a bug fix or behaviour change is applied in one place.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from .models import SkillVariant, VariantResponse
from .sandbox import validate_handler_source, compile_variant_handler

if TYPE_CHECKING:
    from ..skill import Skill
    from .backend import TenantBackend


class VariantOpsError(Exception):
    """Raised by ops functions when a request cannot be fulfilled."""
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _count_all_variants(backend: TenantBackend, tenant_id: str, skill_name: str) -> int:
    return sum(
        1 for v in backend.registry.list_all_for_tenant(tenant_id)
        if v.base_skill_name == skill_name
    )


def _validate_and_compile(backend: TenantBackend, skill_name: str, source_code: str) -> Any:
    violations = validate_handler_source(source_code, backend.sandbox_import_blocklist)
    if violations:
        raise VariantOpsError(
            f"Handler source failed validation: {violations}",
            status=422,
        )
    try:
        return compile_variant_handler(source_code, skill_name, str(uuid.uuid4()))
    except ValueError as exc:
        raise VariantOpsError(str(exc), status=422) from exc


async def op_clone(
    backend: TenantBackend,
    base_skills: dict[str, Skill],
    tenant_id: str,
    skill_name: str,
) -> VariantResponse:
    skill = base_skills.get(skill_name)
    if skill is None:
        raise VariantOpsError(f"Base skill '{skill_name}' not found", status=404)

    if _count_all_variants(backend, tenant_id, skill_name) >= backend.max_variants_per_tenant_per_skill:
        raise VariantOpsError(
            f"Max variants ({backend.max_variants_per_tenant_per_skill}) reached for this skill",
            status=409,
        )

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
    )


async def op_customize(
    backend: TenantBackend,
    base_skills: dict[str, Skill],
    tenant_id: str,
    skill_name: str,
    source_code: str,
    auto_promote: bool = False,
    meta_overrides: dict | None = None,
) -> VariantResponse:
    if not source_code.strip():
        raise VariantOpsError("source_code is required", status=422)

    skill = base_skills.get(skill_name)
    if skill is None:
        raise VariantOpsError(f"Base skill '{skill_name}' not found", status=404)

    if _count_all_variants(backend, tenant_id, skill_name) >= backend.max_variants_per_tenant_per_skill:
        raise VariantOpsError(
            f"Max variants ({backend.max_variants_per_tenant_per_skill}) reached",
            status=409,
        )

    effective_auto_promote = auto_promote or backend.auto_promote
    overrides = meta_overrides or {}
    handler = _validate_and_compile(backend, skill_name, source_code)
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
    )


async def op_promote(
    backend: TenantBackend,
    base_skills: dict[str, Skill],
    tenant_id: str,
    skill_name: str,
    variant_id: str,
) -> VariantResponse:
    if base_skills.get(skill_name) is None:
        raise VariantOpsError(f"Base skill '{skill_name}' not found", status=404)

    variant = backend.registry.get_variant(variant_id)
    if variant is None or variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
        raise VariantOpsError("Variant not found", status=404)

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
    )


async def op_demote(
    backend: TenantBackend,
    base_skills: dict[str, Skill],
    tenant_id: str,
    skill_name: str,
    variant_id: str,
) -> VariantResponse:
    if base_skills.get(skill_name) is None:
        raise VariantOpsError(f"Base skill '{skill_name}' not found", status=404)

    variant = backend.registry.get_variant(variant_id)
    if variant is None or variant.tenant_id != tenant_id or variant.base_skill_name != skill_name:
        raise VariantOpsError("Variant not found", status=404)

    backend.registry.demote(variant)
    variant.status = "sandbox"
    await backend.storage.demote_variant(variant_id)

    return VariantResponse(
        variant_id=variant_id,
        tenant_id=tenant_id,
        base_skill_name=skill_name,
        status="sandbox",
    )
