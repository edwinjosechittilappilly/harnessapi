---
title: Connect to Claude Desktop
description: How to connect your harnessapi skills to Claude Desktop and Cursor as MCP tools.
---

Every harnessapi skill is automatically registered as an MCP tool. Connecting to Claude Desktop or Cursor takes under a minute.

## Claude Desktop

1. **Start your server**

   ```bash
   harnessapi run
   ```

2. **Edit Claude Desktop config**

   Open `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

   ```json
   {
     "mcpServers": {
       "my-skills": {
         "url": "http://localhost:8000/mcp"
       }
     }
   }
   ```

3. **Restart Claude Desktop**

   Your skills appear in the tools panel. Claude can now call them during any conversation.

## Cursor

1. Open **Cursor Settings** → **MCP** → **Add Server**

2. Add:

   ```json
   {
     "my-skills": {
       "url": "http://localhost:8000/mcp"
     }
   }
   ```

3. Save and reload. Skills appear as tools Cursor's AI can call.

## Verify connection

Ask Claude or Cursor:

> "What tools do you have available?"

Your skill names and descriptions should appear in the response.

## Tool naming

The MCP tool name is the skill folder name. Customize it in `skill.toml`:

```toml
[skill]
description = "Summarize text to a target length. Use when asked to shorten or condense text."
```

Write the description as an instruction to the LLM — it directly controls when the model chooses to call your tool.

## Production

For production, deploy harnessapi to a server with a public URL and update the config:

```json
{
  "mcpServers": {
    "my-skills": {
      "url": "https://your-domain.com/mcp"
    }
  }
}
```

See [Deploy to production](/guides/deploy/) for deployment options.
