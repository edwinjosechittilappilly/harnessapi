"""Tests for MCP tool registration."""
import pytest
from harnessapi.mcp import build_mcp_server, register_skill_as_mcp_tool

pytestmark = pytest.mark.integration
from harnessapi.skill import Skill, SkillMeta
from harnessapi.models import SkillInput, SkillOutput


class _Input(SkillInput):
    text: str


class _Output(SkillOutput):
    result: str


def _make_skill(handler, *, name="test", is_mcp=True) -> Skill:
    return Skill(
        meta=SkillMeta(name=name, description="test skill", is_mcp=is_mcp, timeout_secs=5),
        input_model=_Input,
        output_model=_Output,
        handler=handler,
        edit_handler=None,
        folder=None,
    )


# ── Tool registration ─────────────────────────────────────────────────────────

async def test_non_mcp_skill_not_registered():
    mcp = build_mcp_server("test")

    async def handler(input: _Input) -> _Output:
        return _Output(result=input.text)

    skill = _make_skill(handler, is_mcp=False)
    register_skill_as_mcp_tool(mcp, skill)
    tools = await mcp.list_tools()
    assert not any(t.name == "test" for t in tools)


async def test_mcp_skill_registered():
    mcp = build_mcp_server("test")

    async def handler(input: _Input) -> _Output:
        return _Output(result=input.text.upper())

    skill = _make_skill(handler, name="upcase")
    register_skill_as_mcp_tool(mcp, skill)
    tools = await mcp.list_tools()
    assert any(t.name == "upcase" for t in tools)


async def test_streaming_skill_registered_as_tool():
    mcp = build_mcp_server("test")

    async def handler(input: _Input):
        for word in input.text.split():
            yield word

    skill = _make_skill(handler, name="streamer")
    register_skill_as_mcp_tool(mcp, skill)
    tools = await mcp.list_tools()
    assert any(t.name == "streamer" for t in tools)


async def test_tool_description_matches_skill():
    mcp = build_mcp_server("test")

    async def handler(input: _Input) -> _Output:
        return _Output(result=input.text)

    skill = Skill(
        meta=SkillMeta(name="described", description="My custom description"),
        input_model=_Input,
        output_model=_Output,
        handler=handler,
        edit_handler=None,
        folder=None,
    )
    register_skill_as_mcp_tool(mcp, skill)
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "described")
    assert tool.description == "My custom description"


# ── Tool execution ────────────────────────────────────────────────────────────

async def test_mcp_tool_call_returns_result():
    mcp = build_mcp_server("test")

    async def handler(input: _Input) -> _Output:
        return _Output(result=input.text.upper())

    skill = _make_skill(handler, name="exec_test")
    register_skill_as_mcp_tool(mcp, skill)
    result = await mcp.call_tool("exec_test", {"input": {"text": "hello"}})
    assert result is not None


async def test_mcp_streaming_tool_call():
    mcp = build_mcp_server("test")

    async def handler(input: _Input):
        for word in input.text.split():
            yield word

    skill = _make_skill(handler, name="stream_exec")
    register_skill_as_mcp_tool(mcp, skill)
    result = await mcp.call_tool("stream_exec", {"input": {"text": "a b c"}})
    assert result is not None


# ── App-level MCP ─────────────────────────────────────────────────────────────

async def test_harness_app_registers_mcp_tools(app):
    mcp = app._mcp
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert "greet" in tool_names
    assert "echo_stream" in tool_names
    assert "with_defaults" in tool_names


async def test_mcp_endpoint_mounted(app):
    # Verify the MCP sub-application is mounted at /mcp
    mount_paths = [r.path for r in app.routes]
    assert "/mcp" in mount_paths
