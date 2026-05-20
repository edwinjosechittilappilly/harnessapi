from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from sse_starlette.sse import EventSourceResponse, ServerSentEvent

if TYPE_CHECKING:
    from .skill import Skill
    from .models import SkillInput


async def skill_sse_generator(
    skill: Skill,
    input_obj: SkillInput,
) -> AsyncGenerator[ServerSentEvent, None]:
    handler = skill.effective_handler
    timeout = skill.meta.timeout_secs
    try:
        if skill.is_streaming_handler():
            async def _stream():
                async for chunk in handler(input_obj):
                    yield ServerSentEvent(data=str(chunk), event="chunk")
                yield ServerSentEvent(data="", event="done")

            async for event in _stream():
                yield event
        else:
            if timeout is not None:
                result = await asyncio.wait_for(handler(input_obj), timeout=timeout)
            else:
                result = await handler(input_obj)
            yield ServerSentEvent(data=result.model_dump_json(), event="result")
            yield ServerSentEvent(data="", event="done")
    except asyncio.TimeoutError:
        yield ServerSentEvent(data=f"Skill '{skill.meta.name}' timed out", event="error")
    except Exception as exc:
        yield ServerSentEvent(data=str(exc), event="error")


def make_sse_response(skill: Skill, input_obj: SkillInput) -> EventSourceResponse:
    return EventSourceResponse(skill_sse_generator(skill, input_obj))


async def _handler_sse_generator(
    handler,
    is_streaming: bool,
    input_obj: SkillInput,
    timeout: float | None,
) -> AsyncGenerator[ServerSentEvent, None]:
    try:
        if is_streaming:
            async def _stream():
                async for chunk in handler(input_obj):
                    yield ServerSentEvent(data=str(chunk), event="chunk")
                yield ServerSentEvent(data="", event="done")
            async for event in _stream():
                yield event
        else:
            if timeout is not None:
                result = await asyncio.wait_for(handler(input_obj), timeout=timeout)
            else:
                result = await handler(input_obj)
            yield ServerSentEvent(data=result.model_dump_json(), event="result")
            yield ServerSentEvent(data="", event="done")
    except asyncio.TimeoutError:
        yield ServerSentEvent(data="Handler timed out", event="error")
    except Exception as exc:
        yield ServerSentEvent(data=str(exc), event="error")


def make_sse_response_for_handler(
    handler,
    is_streaming: bool,
    input_obj: SkillInput,
    timeout: float | None,
) -> EventSourceResponse:
    return EventSourceResponse(_handler_sse_generator(handler, is_streaming, input_obj, timeout))
