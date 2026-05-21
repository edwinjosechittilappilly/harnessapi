from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError

from .edit import EditRequest, EditResponse, apply_edit
from .streaming import make_sse_response

if TYPE_CHECKING:
    from .skill import Skill
    from .multitenancy.registry import TenantSkillRegistry


class SkillRoute(APIRoute):
    """POST /skills/{name} — SSE by default, JSON when Accept: application/json."""

    def __init__(self, skill: Skill, tenant_registry: TenantSkillRegistry | None = None, **kwargs) -> None:
        self._skill = skill
        self._tenant_registry = tenant_registry
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
        tenant_registry = self._tenant_registry

        async def endpoint(request: Request):
            body = await request.json()

            # Tenant-aware handler resolution
            handler = skill.effective_handler
            is_streaming = skill.is_streaming_handler()
            timeout = skill.meta.timeout_secs

            if tenant_registry is not None:
                tenant_id = getattr(request.state, "tenant_id", None)
                if tenant_id is not None:
                    variant = tenant_registry.get_promoted(tenant_id, skill.meta.name)
                    if variant is not None:
                        handler = variant.handler
                        is_streaming = variant.is_streaming_handler()

            try:
                input_obj = skill.input_model.model_validate(body)
            except ValidationError as exc:
                return JSONResponse(status_code=422, content={"detail": exc.errors()})
            accept = request.headers.get("accept", "")
            if "application/json" in accept:
                if is_streaming:
                    chunks: list[str] = []
                    async for chunk in handler(input_obj):
                        chunks.append(str(chunk))
                    return JSONResponse(content={"chunks": chunks})
                else:
                    import asyncio
                    if timeout is not None:
                        result = await asyncio.wait_for(handler(input_obj), timeout=timeout)
                    else:
                        result = await handler(input_obj)
                    return JSONResponse(content=result.model_dump())
            # SSE path: if using a variant handler, wrap it like a Skill would
            if handler is not skill.effective_handler:
                from .streaming import make_sse_response_for_handler
                return make_sse_response_for_handler(handler, is_streaming, input_obj, timeout)
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
