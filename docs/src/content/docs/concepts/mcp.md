---
title: MCP tools
description: How harnessapi automatically registers every skill as a Model Context Protocol (MCP) tool for Claude, Cursor, and any agent.
---

Every skill is automatically registered as a [Model Context Protocol (MCP)](https://modelcontextprotocol.io) tool — no extra code, no schema files, no separate server.

## How it works

When `HarnessAPI` starts, it:

1. Discovers skill folders in `skills_dir`
2. Registers each skill as an HTTP endpoint at `POST /skills/{name}`
3. Registers each skill as an MCP tool at `/mcp`

The MCP tool schema is derived from the skill's Pydantic `Input` model. No manual schema definition.

## Connect Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "my-skills": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Restart Claude Desktop. Your skills appear as tools Claude can call.

## Connect Cursor

Open Cursor Settings → MCP → Add Server:

```json
{
  "my-skills": {
    "url": "http://localhost:8000/mcp"
  }
}
```

## Disable MCP for a specific skill

Set `is_mcp = false` in `skill.toml`:

```toml
[skill]
description = "Internal skill — not exposed as MCP tool"
is_mcp      = false
```

## Streaming and MCP

MCP tools are request-response. Streaming handlers are fully supported — harnessapi collects all yielded chunks and joins them as a single string for MCP clients.

## MCP server name

Customize the server name shown in MCP clients:

```python
app = HarnessAPI(
    skills_dir="./skills",
    mcp_server_name="My Skills Server",
)
```

## MCP endpoint

The MCP server runs as a mounted ASGI app:

| Path | Protocol |
|------|----------|
| `/mcp` | FastMCP HTTP (SSE-based MCP transport) |
