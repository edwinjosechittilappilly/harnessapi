import asyncio
from typing import Any

from fastmcp import FastMCP

from .skill import Skill


def build_mcp_server(name: str = "HarnessAPI") -> FastMCP:
    return FastMCP(name=name)


def register_skill_as_mcp_tool(mcp: FastMCP, skill: Skill) -> None:
    if not skill.meta.is_mcp:
        return

    _make_and_register(mcp, skill)


def _make_and_register(mcp: FastMCP, skill: Skill) -> None:
    input_model = skill.input_model
    is_streaming = skill.is_streaming_handler()
    handler = skill.effective_handler
    skill_name = skill.meta.name
    skill_desc = skill.meta.description
    timeout = skill.meta.timeout_secs

    # Build the wrapper source so the annotation resolves at definition time.
    # FastMCP 3.x inspects __annotations__ — the model must be in the function's
    # global namespace, not just the enclosing scope.
    globs = {
        "asyncio": asyncio,
        "Any": Any,
        "input_model": input_model,
        "handler": handler,
        "is_streaming": is_streaming,
        "timeout": timeout,
    }
    src = (
        "async def mcp_wrapper(input: input_model) -> Any:\n"
        "    if is_streaming:\n"
        "        chunks = []\n"
        "        async for chunk in handler(input):\n"
        "            chunks.append(str(chunk))\n"
        "        return '\\n'.join(chunks)\n"
        "    else:\n"
        "        if timeout is not None:\n"
        "            result = await asyncio.wait_for(handler(input), timeout=timeout)\n"
        "        else:\n"
        "            result = await handler(input)\n"
        "        return result.model_dump()\n"
    )
    exec(compile(src, "<mcp_wrapper>", "exec"), globs)
    mcp_wrapper = globs["mcp_wrapper"]
    mcp_wrapper.__name__ = skill_name
    mcp_wrapper.__doc__ = skill_desc

    mcp.tool(name=skill_name, description=skill_desc)(mcp_wrapper)
