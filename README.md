<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/edwinjosechittilappilly/harnessapi/main/assets/logo_long.png" />
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/edwinjosechittilappilly/harnessapi/main/assets/logo_long.png" />
  <img src="https://raw.githubusercontent.com/edwinjosechittilappilly/harnessapi/main/assets/logo_long.png" alt="harnessapi" width="320" />
</picture>

### Python Skill Framework for MCP Tools and Streaming APIs

**Write a skill. Get an API. Get an MCP tool. Ship.**

[![PyPI version](https://img.shields.io/pypi/v/harnessapi.svg "harnessapi on PyPI")](https://pypi.org/project/harnessapi/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg "Requires Python 3.11 or higher")](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg "MIT License")](LICENSE)

[![Built on FastAPI](https://img.shields.io/badge/built%20on-FastAPI-009688?logo=fastapi&logoColor=white "Built on FastAPI")](https://fastapi.tiangolo.com)
[![Powered by FastMCP](https://img.shields.io/badge/powered%20by-FastMCP-6f42c1 "Powered by FastMCP")](https://github.com/jlowin/fastmcp)
[![agentskills.io compatible](https://img.shields.io/badge/agentskills.io-compatible-orange "Compatible with agentskills.io standard")](https://agentskills.io)

</div>

---

**harnessapi** is a Python framework that turns a skill folder into a **streaming HTTP API** and a **Model Context Protocol (MCP) tool** simultaneously — no routes, no decorators, no separate MCP server to maintain.

```
skills/summarize/
├── models.py    ← define input & output
├── handler.py   ← write your logic
└── skill.toml   ← name, description, tags, timeout
```

Drop the folder. Run the server. Your skill is live as an HTTP endpoint, an MCP tool, and in Swagger docs.

---

## Contents

- [Why harnessapi](#why-harnessapi)
- [Quick start](#quick-start)
- [Try it instantly with uvx](#try-it-instantly-with-uvx)
- [Streaming](#streaming--just-use-yield)
- [Every skill is an MCP tool](#every-skill-is-an-mcp-tool)
- [Works with](#works-with)
- [Scaffold in one command](#scaffold-in-one-command)
- [Example: streaming factorial](#example-streaming-factorial-sse--mcp)
- [Skill folder reference](#skill-folder-reference)
- [Hot-swap handlers at runtime](#hot-swap-handlers-at-runtime)
- [Features](#features)
- [Philosophy](#philosophy)
- [See also](#see-also)

---

## Why harnessapi

Use harnessapi when you are:

- Building tools for **Claude Desktop, Cursor, Copilot, or any MCP client**
- Exposing Python functions as **streaming API endpoints** (Server-Sent Events)
- Converting an **agentskills.io** skill folder into a production API
- Shipping an **LLM-powered microservice** without FastAPI boilerplate
- Wrapping any Python function as an **MCP tool** in under a minute

---

## Quick start

```bash
uv add harnessapi
```

**`skills/summarize/models.py`**
```python
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    text: str
    max_length: int = 200

class Output(SkillOutput):
    summary: str
```

**`skills/summarize/handler.py`**
```python
from .models import Input, Output

async def handle(input: Input) -> Output:
    return Output(summary=input.text[:input.max_length])
```

**`skills/summarize/skill.toml`**
```toml
[skill]
description  = "Summarize text to a target length"
is_mcp       = true
tags         = ["text"]
timeout_secs = 30
```

**`main.py`**
```python
from pathlib import Path
from harnessapi import HarnessAPI

app = HarnessAPI(skills_dir=Path(__file__).parent / "skills")
```

```bash
harnessapi run
```

Your skill is live at three places simultaneously:

| Endpoint | Details |
|---|---|
| `POST /skills/summarize` | HTTP endpoint — SSE streaming by default |
| `GET /docs` | Interactive OpenAPI / Swagger UI |
| `http://localhost:8000/mcp` | MCP server — ready for Claude, Cursor, Copilot |

---

## Try it instantly with uvx

No install needed. `uvx` runs harnessapi in an isolated environment:

```bash
# Scaffold a new project
uvx harnessapi init my-project

# Enter and run it
cd my-project
uvx harnessapi run
```

Then call your skill:

```bash
# Streaming (SSE — default)
curl -X POST http://localhost:8000/skills/greet \
  -H "Content-Type: application/json" \
  -d '{"name": "world"}'

# Plain JSON
curl -X POST http://localhost:8000/skills/greet \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"name": "world"}'
```

```json
{"message": "Hello, world! Welcome to harnessapi.", "length": 36}
```

---

## Streaming — just use `yield`

Return a value for a single response. Use `yield` to stream chunks as they're produced. Same endpoint, same URL, no extra config.

```python
# Non-streaming — return a value
async def handle(input: Input) -> Output:
    return Output(result=compute(input))

# Streaming — yield chunks
async def handle(input: Input):
    async for token in llm.stream(input.prompt):
        yield token
```

Clients receive standard Server-Sent Events (SSE):

```
event: chunk
data: The answer is

event: chunk
data: 42.

event: done
data:
```

Need plain JSON? Add `Accept: application/json` — harnessapi collects all chunks and returns them together. Same handler, zero changes.

---

## Every skill is an MCP tool

Every skill folder is automatically registered as a [Model Context Protocol (MCP)](https://modelcontextprotocol.io) tool. No extra code required.

```json
{
  "mcpServers": {
    "my-skills": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Add a skill folder → restart the server → it appears as an MCP tool. No registration. No schema maintenance.

---

## Works with

| Client | How to connect |
|---|---|
| **Claude Desktop** | Add `http://localhost:8000/mcp` as an MCP server in settings |
| **Cursor** | Add under MCP Servers in Cursor settings |
| **Copilot / VS Code** | Any MCP-compatible client works |
| **agentskills.io** | Drop-in compatible — existing skill folders work as-is |
| **Any HTTP client** | `POST /skills/{name}` — curl, httpx, fetch |

---

## Scaffold in one command

```bash
# New project with a sample greet skill
harnessapi init my-project

# Add API + MCP layer to an existing agentskills.io skill folder
harnessapi init --skill .agents/skills/summarize

# Convert an entire skills directory at once
harnessapi init --skills-dir .agents/skills

# Wrap a plain Python function as a skill
harnessapi init --function utils/compute.py --output skills
```

harnessapi is a compatible superset of the [agentskills.io](https://agentskills.io) standard — existing skill folders with a `SKILL.md` are detected automatically.

---

## Example: streaming factorial (SSE + MCP)

```bash
git clone https://github.com/edwinjosechittilappilly/harnessapi
cd harnessapi
uv sync
uv run uvicorn examples.factorial_app.main:app --reload
```

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

Or collect everything as JSON:

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

## Skill folder reference

```
skills/
└── my_skill/
    ├── handler.py        ← required: your logic
    ├── models.py         ← required: Pydantic Input + Output
    ├── SKILL.md          ← optional: agentskills.io compatible metadata
    ├── skill.toml        ← optional: name, description, tags, timeout
    ├── defaults/
    │   └── input.json    ← optional: default values shown in /docs
    └── examples/
        └── 01.json       ← optional: {input, output} pairs for docs
```

**`skill.toml`**
```toml
[skill]
description  = "What this skill does"
is_mcp       = true      # set false to hide from MCP
tags         = ["nlp"]
timeout_secs = 30
```

---

## Hot-swap handlers at runtime

Patch a running skill handler without restarting the server:

```python
app = HarnessAPI(skills_dir="./skills", enable_edit_endpoints=True)
```

```bash
curl -X POST http://localhost:8000/skills/summarize/edit \
  -H "Content-Type: application/json" \
  -d '{"source_code": "async def handle(input):\n    return Output(summary=input.text.upper())", "persist": true}'
```

> Disabled by default. Add auth middleware before enabling in production.

---

## Features

| Feature | Details |
|---|---|
| HTTP endpoint | `POST /skills/{name}` for every skill, automatically |
| Streaming | SSE by default · JSON via `Accept: application/json` |
| MCP server | `/mcp` · all skills auto-registered as MCP tools |
| OpenAPI docs | `/docs` · full Swagger UI, zero config |
| Pydantic validation | Invalid input rejected before your handler runs |
| Timeouts | Per-skill `timeout_secs` in `skill.toml` |
| Hot-swap | Runtime handler replacement via opt-in edit endpoint |
| agentskills.io | Drop-in compatible — existing skill folders just work |
| CLI scaffold | `uvx harnessapi init` · `--skill` · `--skills-dir` · `--function` |

---

## Philosophy

Most frameworks start with routes. Most agent frameworks start with tools. `harnessapi` starts with **skills** — the capability itself. The HTTP API and the MCP tool are consequences, not configuration.

Write the thing. Everything else follows.

---

## See also

- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server framework harnessapi builds on
- [FastAPI](https://fastapi.tiangolo.com) — the HTTP layer underneath
- [agentskills.io](https://agentskills.io) — skill folder standard harnessapi is compatible with
- [Model Context Protocol](https://modelcontextprotocol.io) — the open protocol for agent tools
- [Pydantic](https://docs.pydantic.dev) — data validation for skill inputs and outputs

---

<div align="center">

Built on [FastAPI](https://fastapi.tiangolo.com) · [FastMCP](https://github.com/jlowin/fastmcp) · [Pydantic](https://docs.pydantic.dev) · [uv](https://docs.astral.sh/uv/)

</div>
