from __future__ import annotations

import textwrap
import types
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from .skill import Skill


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
