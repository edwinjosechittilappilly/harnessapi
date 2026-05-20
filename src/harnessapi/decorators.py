from __future__ import annotations

import functools
from typing import Callable

from .models import SkillInput, SkillOutput
from .skill import Skill, SkillMeta

_registry: dict[str, Skill] = {}


def skill(
    name: str | None = None,
    *,
    description: str | None = None,
    is_mcp: bool = True,
    tags: list[str] | None = None,
    timeout_secs: float | None = 30.0,
    input_model: type[SkillInput] | None = None,
    output_model: type[SkillOutput] | None = None,
) -> Callable:
    """Decorator to register a skill without a folder.

    Usage::

        @skill(name="greet", input_model=GreetInput, output_model=GreetOutput)
        async def greet(input: GreetInput) -> GreetOutput: ...
    """
    def decorator(fn: Callable) -> Callable:
        skill_name = name or fn.__name__
        in_model = input_model
        out_model = output_model

        if in_model is None or out_model is None:
            hints = getattr(fn, "__annotations__", {})
            if in_model is None:
                in_model = hints.get("input") or hints.get("return")
            if out_model is None:
                out_model = hints.get("return")

        if in_model is None or out_model is None:
            raise TypeError(
                f"@skill('{skill_name}'): provide input_model and output_model, "
                "or annotate the function with Input and return types."
            )

        meta = SkillMeta(
            name=skill_name,
            description=description or fn.__doc__ or "",
            is_mcp=is_mcp,
            tags=tags or [],
            timeout_secs=timeout_secs,
        )
        s = Skill(
            meta=meta,
            input_model=in_model,
            output_model=out_model,
            handler=fn,
            edit_handler=None,
            folder=None,
        )
        _registry[skill_name] = s

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            return await fn(*args, **kwargs)

        wrapper.__skill__ = s  # type: ignore[attr-defined]
        return wrapper

    return decorator


def get_registered_skills() -> list[Skill]:
    return list(_registry.values())
