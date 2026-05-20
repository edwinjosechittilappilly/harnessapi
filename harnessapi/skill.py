from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .models import SkillInput, SkillOutput


@dataclass
class SkillMeta:
    # core
    name: str
    description: str
    is_mcp: bool = True
    tags: list[str] = field(default_factory=list)
    timeout_secs: float | None = 30.0
    # agentskills.io standard fields
    license: str | None = None
    compatibility: str | None = None   # e.g. "Python 3.11+"
    allowed_tools: list[str] = field(default_factory=list)
    argument_hint: str | None = None
    instructions: str | None = None    # full SKILL.md Markdown body


@dataclass
class Skill:
    meta: SkillMeta
    input_model: type[SkillInput]
    output_model: type[SkillOutput]
    handler: Callable
    edit_handler: Callable | None
    folder: Path | None
    examples: list[dict[str, Any]] = field(default_factory=list)
    defaults: dict[str, Any] | None = None

    @property
    def effective_handler(self) -> Callable:
        return self.edit_handler if self.edit_handler is not None else self.handler

    def is_streaming_handler(self) -> bool:
        return inspect.isasyncgenfunction(self.effective_handler)
