---
title: MCP tools
description: How harnessapi automatically registers every skill as a Model Context Protocol tool, and how to connect Claude Desktop, Claude Code, Cursor, and other clients.
---

Every skill is automatically registered as a [Model Context Protocol (MCP)](https://modelcontextprotocol.io) tool — no extra code, no schema files, no separate server process to manage.

---

## What is MCP?

Model Context Protocol is an open standard for connecting AI agents to tools and data. Instead of writing glue code to call your API, an MCP-aware agent (Claude Desktop, Claude Code, Cursor, Copilot) discovers your tools at connection time and calls them natively — with proper schema validation, structured outputs, and no HTTP plumbing in the agent's code.

harnessapi implements MCP using [FastMCP](https://github.com/jlowin/fastmcp) and mounts the MCP server at `/mcp` alongside your skill endpoints.

---

## How skills become MCP tools

When `HarnessAPI` starts, for each skill it:

1. **Reads `Input`** — generates the MCP tool input schema from the Pydantic model fields, types, and defaults
2. **Uses `skill.toml` metadata** — the `description` becomes the tool description shown to the agent
3. **Wraps the handler** — calling the MCP tool calls your `handle()` function
4. **Handles streaming** — streaming handlers (`yield`) are fully supported; harnessapi collects all yielded chunks and returns them joined as a single string to the MCP client (MCP is request-response)

The tool name is the skill name (folder name or `name` in `skill.toml`). No manual schema definition required — the Pydantic model is the schema.

---

## Live tool list

The MCP server is dynamic. When you:

- **Add a skill folder** — restart the server, the tool appears
- **Remove a skill folder** — restart the server, the tool disappears
- **Update `skill.toml`** — restart to pick up name or description changes

No tool registration code to update. The skill folder is the source of truth.

---

## Connect Claude Desktop

Add to the Claude Desktop MCP config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "my-skills": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Restart Claude Desktop. Your skills appear in the tool picker — Claude can call them directly during a conversation.

---

## Connect Claude Code

Claude Code supports MCP servers via the CLI:

```bash
claude mcp add my-skills http://localhost:8000/mcp
```

Or add it manually in Claude Code settings under **MCP Servers**. The skills appear as tools available in any Claude Code session.

---

## Connect Cursor

Open **Cursor Settings → MCP → Add Server**:

```json
{
  "my-skills": {
    "url": "http://localhost:8000/mcp"
  }
}
```

---

## Connect VS Code / GitHub Copilot

Any MCP-compatible client works. In VS Code with the Copilot extension, add the server URL in the MCP settings panel. Check your client's documentation for the exact location — the URL is always `http://localhost:8000/mcp`.

---

## Tool naming

The MCP tool name matches the skill name exactly:

| Folder | `skill.toml` name override | MCP tool name |
|---|---|---|
| `greet/` | — | `greet` |
| `summarize-text/` | — | `summarize-text` |
| `my_skill/` | `name = "process"` | `process` |

Agents reference tools by this name. Keep names descriptive and stable — renaming a tool breaks existing agent workflows that reference it by name.

---

## Disabling MCP for a skill

Set `is_mcp = false` in `skill.toml` to exclude a skill from the MCP server while keeping its HTTP endpoint active:

```toml
[skill]
description = "Internal skill — HTTP only, not exposed as MCP tool"
is_mcp      = false
```

This is useful for internal or admin skills that should not be callable by external agents.

---

## MCP and streaming

MCP is a request-response protocol — there is no native streaming. When a streaming handler is called via MCP:

1. harnessapi calls the handler and collects all yielded chunks
2. Joins them as a single string
3. Returns the joined string as the MCP tool result

For clients that need streaming output, use the HTTP endpoint (`POST /skills/{name}`) directly instead of MCP.

---

## MCP and multi-tenancy

The `/mcp` endpoint is always **tenant-agnostic** — it serves base skill handlers only. It has no concept of `X-Tenant-ID` or promoted variants.

For agent-driven **management** of per-user variants (clone, customize, promote, sandbox), use the **Admin MCP server** at `/admin-mcp`. See [Admin MCP server](/harnessapi/multi-tenancy/admin-mcp) for setup.

---

## MCP server name

Customize the server name shown in MCP client UIs:

```python
app = HarnessAPI(
    skills_dir="./skills",
    mcp_server_name="My Skills Server",
)
```

---

## MCP endpoints

| Path | Protocol | Purpose |
|------|----------|---------|
| `/mcp` | FastMCP HTTP (SSE transport) | Skill tools — tenant-agnostic |
| `/admin-mcp` | FastMCP HTTP | Variant management tools — requires `enable_admin_mcp=True` |

---

## See also

- [Skill folders](/harnessapi/concepts/skill-folders) — how `Input` models become tool schemas
- [Streaming (SSE)](/harnessapi/concepts/streaming) — how streaming differs between HTTP and MCP
- [Admin MCP server](/harnessapi/multi-tenancy/admin-mcp) — agent-native multi-tenancy management
- [Connect to Claude Desktop](/harnessapi/guides/claude-desktop) — detailed Claude Desktop setup guide
