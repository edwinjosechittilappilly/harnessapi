# Factorial App — harnessapi example

A minimal harnessapi project showing a **streaming skill** that computes factorial step-by-step, also exposed as an MCP tool.

```
POST /skills/factorial   ← compute n!, streaming each multiplication step
GET  /mcp                ← factorial as an MCP tool
GET  /docs               ← Swagger UI
```

---

## Scaffold this example

```bash
# Install harnessapi if you haven't already
uv tool install harnessapi        # recommended
# pip install harnessapi          # alternative

# List all bundled examples
harnessapi examples

# Scaffold into ./factorial_app/
harnessapi examples factorial_app

# Or scaffold into a custom directory
harnessapi examples factorial_app my-factorial
```

---

## Setup

```bash
cd factorial_app
uv sync
```

---

## Run

```bash
harnessapi run
# or: uvicorn main:app --reload
```

Server starts at `http://localhost:8000`.

---

## Usage

### Streaming (SSE — default)

```bash
curl -X POST http://localhost:8000/skills/factorial \
  -H "Content-Type: application/json" \
  -d '{"n": 5}'
```

```
event: chunk
data: start: 1

event: chunk
data: 2: 2

event: chunk
data: 3: 6

event: chunk
data: 4: 24

event: chunk
data: 5: 120

event: done
data:
```

### JSON response

```bash
curl -X POST http://localhost:8000/skills/factorial \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"n": 5}'
```

```json
{"chunks": ["start: 1", "2: 2", "3: 6", "4: 24", "5: 120"]}
```

---

## MCP tool — Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "factorial": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

The `factorial` skill appears as an MCP tool. Ask Claude: *"What is 10 factorial?"* and it will call the tool automatically.
