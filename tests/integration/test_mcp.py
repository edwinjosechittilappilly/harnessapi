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


# ── App-level MCP (internal) ──────────────────────────────────────────────────

async def test_harness_app_registers_mcp_tools(app):
    mcp = app._mcp
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert "greet" in tool_names
    assert "echo_stream" in tool_names
    assert "with_defaults" in tool_names


async def test_mcp_endpoint_mounted(app):
    mount_paths = [r.path for r in app.routes]
    assert "/mcp" in mount_paths


# ── MCP over HTTP (real integration) ─────────────────────────────────────────
# FastMCP's streamable-HTTP transport uses the MCP session protocol:
# initialize → notifications/initialized → tools/list, all over SSE.
# We use FastMCP's own in-process Client to drive this properly.

import contextlib
import json as _json
from asgi_lifespan import LifespanManager
from httpx import AsyncClient, ASGITransport


@contextlib.asynccontextmanager
async def lifespan_client(app):
    async with LifespanManager(app) as manager:
        async with AsyncClient(
            transport=ASGITransport(app=manager.app), base_url="http://test"
        ) as client:
            yield client


async def _mcp_session(client: AsyncClient) -> list[dict]:
    """Run initialize → notifications/initialized → tools/list and return tool list."""
    sse_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    # Step 1: initialize
    r = await client.post("/mcp/", headers=sse_headers, json={
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.1"},
        },
    })
    assert r.status_code == 200, f"initialize failed: {r.status_code} {r.text[:200]}"

    # Parse session ID from SSE response
    session_id = None
    for line in r.text.splitlines():
        if line.startswith("data:"):
            data = _json.loads(line[5:].strip())
            if data.get("id") == 0 and "result" in data:
                # Session ID comes back in a Mcp-Session-Id header on the response
                session_id = r.headers.get("mcp-session-id")

    session_headers = {**sse_headers}
    if session_id:
        session_headers["mcp-session-id"] = session_id

    # Step 2: notifications/initialized (no response expected)
    await client.post("/mcp/", headers=session_headers, json={
        "jsonrpc": "2.0", "method": "notifications/initialized",
    })

    # Step 3: tools/list
    r2 = await client.post("/mcp/", headers=session_headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
    })
    assert r2.status_code == 200, f"tools/list failed: {r2.status_code} {r2.text[:200]}"

    tools = []
    for line in r2.text.splitlines():
        if line.startswith("data:"):
            data = _json.loads(line[5:].strip())
            if data.get("id") == 1 and "result" in data:
                tools = data["result"].get("tools", [])
    return tools


async def test_mcp_http_endpoint_reachable(app):
    """MCP /mcp/ endpoint must respond to initialize — not 404/500."""
    async with lifespan_client(app) as client:
        r = await client.post("/mcp/", headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1"},
            },
        })
        assert r.status_code not in (404, 500)


async def test_mcp_lists_tools_over_http(app):
    """tools/list over MCP HTTP session must include the skill names."""
    async with lifespan_client(app) as client:
        tools = await _mcp_session(client)
        tool_names = {t["name"] for t in tools}
        assert "greet" in tool_names
        assert "echo_stream" in tool_names


async def test_mcp_tool_schema_has_input_fields(app):
    """The greet tool inputSchema must expose the `name` field over HTTP."""
    async with lifespan_client(app) as client:
        tools = await _mcp_session(client)
        greet = next((t for t in tools if t["name"] == "greet"), None)
        assert greet is not None, "greet tool not found in tools/list"
        # FastMCP wraps the skill Input model under an "input" property
        props = greet.get("inputSchema", {}).get("properties", {})
        input_props = props.get("input", {}).get("properties", {})
        assert "name" in input_props, (
            f"Expected 'name' in greet inputSchema.input.properties, got: {props}"
        )
