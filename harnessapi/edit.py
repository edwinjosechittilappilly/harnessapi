from __future__ import annotations

import textwrap
import types
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from .skill import Skill
    from .multitenancy.models import SkillVariant


class EditRequest(BaseModel):
    source_code: str
    persist: bool = False


class EditResponse(BaseModel):
    status: str
    skill_name: str
    error: str | None = None


def apply_edit(skill: Skill, request: EditRequest) -> None:
    """Compile source_code and hot-swap skill.edit_handler.

    Executes arbitrary Python — only expose this endpoint with auth in production.
    """
    source = textwrap.dedent(request.source_code)
    module = types.ModuleType(f"_skill_{skill.meta.name}_edit_runtime")
    try:
        exec(compile(source, "<edit>", "exec"), module.__dict__)
    except SyntaxError as exc:
        raise ValueError(f"Syntax error in submitted handler: {exc}") from exc

    handle_fn = getattr(module, "handle", None)
    if handle_fn is None:
        raise ValueError("Submitted source must define a `handle` function")

    skill.edit_handler = handle_fn

    if request.persist and skill.folder is not None:
        edit_dir = skill.folder / "edit"
        edit_dir.mkdir(exist_ok=True)
        (edit_dir / "handler.py").write_text(request.source_code)


def apply_variant_edit(variant: SkillVariant, source_code: str) -> None:
    """Validate source_code statically, then compile and hot-swap variant.handler.

    Unlike apply_edit, this runs the AST validator before exec() to reject
    obvious unsafe patterns. Use for agent-submitted code in multi-tenant mode.
    """
    from .multitenancy.sandbox import validate_handler_source, compile_variant_handler

    violations = validate_handler_source(source_code)
    if violations:
        raise ValueError("Handler source failed validation: " + "; ".join(violations))

    handler = compile_variant_handler(source_code, variant.base_skill_name, variant.variant_id)
    variant.handler = handler
    variant.handler_source = source_code
