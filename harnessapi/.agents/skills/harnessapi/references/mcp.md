# MCP integration in harnessapi

## How it works

Every skill with `is_mcp = true` (the default) is automatically registered as an MCP tool on the FastMCP server mounted at `/mcp`. No extra code needed.

## Connect Claude Desktop

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "my-app": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## Connect Cursor

In Cursor settings → MCP → Add server:
- Name: `my-app`
- URL: `http://localhost:8000/mcp`

## Connect any MCP client

The MCP endpoint uses the standard MCP HTTP+SSE transport.

Initialize:
```bash
curl -X POST http://localhost:8000/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}'
```

## Disable MCP for a specific skill

In `skill.toml`:
```toml
[skill]
is_mcp = false
```

Or in the `@skill` decorator:
```python
@skill(name="internal", is_mcp=False, ...)
async def handler(input: Input) -> Output: ...
```

## MCP tool schema

The tool name is the skill name. The tool input schema is derived from the skill's `Input` Pydantic model. The tool accepts a single `input` parameter of that type.

## Streaming and MCP

MCP tools are request-response (not streaming). Streaming handlers work fine — harnessapi collects all chunks and returns them joined as one string. The SSE stream is HTTP-only.

## Add the harnessapi package skill to your project

Make harnessapi skills discoverable by your coding agent:
```bash
cp -r $(python -c "import harnessapi, os; print(os.path.dirname(harnessapi.__file__))")/.agents/skills/harnessapi .agents/skills/
```

This copies the bundled `harnessapi` skill into your project's `.agents/skills/`, where Claude Code, Cursor, and Copilot will discover it automatically.
