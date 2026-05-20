from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from .edit import EditRequest, EditResponse, apply_edit
from .streaming import make_sse_response

if TYPE_CHECKING:
    from .skill import Skill


class SkillRoute(APIRoute):
    """POST /skills/{name} — SSE by default, JSON when Accept: application/json."""

    def __init__(self, skill: Skill, **kwargs) -> None:
        self._skill = skill
        endpoint = self._make_endpoint()
        super().__init__(
            path=f"/skills/{skill.meta.name}",
            endpoint=endpoint,
            methods=["POST"],
            tags=skill.meta.tags or ["skills"],
            summary=skill.meta.name,
            description=skill.meta.description,
            **kwargs,
        )

    def _make_endpoint(self):
        skill = self._skill

        async def endpoint(request: Request):
            body = await request.json()
            input_obj = skill.input_model.model_validate(body)
            accept = request.headers.get("accept", "")
            if "application/json" in accept:
                if skill.is_streaming_handler():
                    chunks: list[str] = []
                    async for chunk in skill.effective_handler(input_obj):
                        chunks.append(str(chunk))
                    return JSONResponse(content={"chunks": chunks})
                else:
                    import asyncio
                    timeout = skill.meta.timeout_secs
                    if timeout is not None:
                        result = await asyncio.wait_for(
                            skill.effective_handler(input_obj), timeout=timeout
                        )
                    else:
                        result = await skill.effective_handler(input_obj)
                    return JSONResponse(content=result.model_dump())
            return make_sse_response(skill, input_obj)

        endpoint.__name__ = f"skill_{skill.meta.name}"
        return endpoint


class EditRoute(APIRoute):
    """POST /skills/{name}/edit — hot-swap the skill handler."""

    def __init__(self, skill: Skill, **kwargs) -> None:
        self._skill = skill
        endpoint = self._make_endpoint()
        super().__init__(
            path=f"/skills/{skill.meta.name}/edit",
            endpoint=endpoint,
            methods=["POST"],
            tags=["skills", "edit"],
            summary=f"Edit handler: {skill.meta.name}",
            response_model=EditResponse,
            **kwargs,
        )

    def _make_endpoint(self):
        skill = self._skill

        async def endpoint(body: EditRequest) -> EditResponse:
            try:
                apply_edit(skill, body)
                return EditResponse(status="ok", skill_name=skill.meta.name)
            except ValueError as exc:
                return EditResponse(status="error", skill_name=skill.meta.name, error=str(exc))

        endpoint.__name__ = f"edit_{skill.meta.name}"
        return endpoint
