"""Tests for streaming helpers and SSE generator."""
import asyncio
import pytest

pytestmark = pytest.mark.unit

from harnessapi.streaming import skill_sse_generator
from harnessapi.skill import Skill, SkillMeta
from harnessapi.models import SkillInput, SkillOutput


class _Input(SkillInput):
    text: str


class _Output(SkillOutput):
    result: str


def _make_skill(handler, *, is_mcp=False) -> Skill:
    return Skill(
        meta=SkillMeta(name="test", description="test", is_mcp=is_mcp, timeout_secs=5),
        input_model=_Input,
        output_model=_Output,
        handler=handler,
        edit_handler=None,
        folder=None,
    )


async def _collect(skill, input_obj):
    events = []
    async for ev in skill_sse_generator(skill, input_obj):
        events.append((ev.event, ev.data))
    return events


async def test_non_streaming_emits_result_then_done():
    async def handler(input: _Input) -> _Output:
        return _Output(result=input.text.upper())

    skill = _make_skill(handler)
    events = await _collect(skill, _Input(text="hello"))
    event_types = [e[0] for e in events]
    assert event_types == ["result", "done"]
    assert "HELLO" in events[0][1]


async def test_streaming_emits_chunks_then_done():
    async def handler(input: _Input):
        for word in input.text.split():
            yield word

    skill = _make_skill(handler)
    events = await _collect(skill, _Input(text="a b c"))
    event_types = [e[0] for e in events]
    assert event_types == ["chunk", "chunk", "chunk", "done"]
    assert [e[1] for e in events[:3]] == ["a", "b", "c"]


async def test_handler_exception_emits_error():
    async def handler(input: _Input) -> _Output:
        raise ValueError("boom")

    skill = _make_skill(handler)
    events = await _collect(skill, _Input(text="x"))
    assert events[0][0] == "error"
    assert "boom" in events[0][1]


async def test_streaming_exception_emits_error():
    async def handler(input: _Input):
        yield "first"
        raise RuntimeError("mid-stream error")

    skill = _make_skill(handler)
    events = await _collect(skill, _Input(text="x"))
    types = [e[0] for e in events]
    assert "chunk" in types
    assert "error" in types


async def test_timeout_emits_error():
    async def handler(input: _Input) -> _Output:
        await asyncio.sleep(10)
        return _Output(result="never")

    skill = _make_skill(handler)
    skill.meta.timeout_secs = 0.05
    events = await _collect(skill, _Input(text="x"))
    assert events[0][0] == "error"
    assert "timed out" in events[0][1]
