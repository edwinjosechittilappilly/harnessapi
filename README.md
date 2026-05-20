<div align="center">

# harnessapi

### Write a skill. Get an API. Get an MCP tool. Ship.

[![PyPI version](https://img.shields.io/pypi/v/harnessapi.svg)](https://pypi.org/project/harnessapi/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

One folder. Two files. You get a **streaming HTTP endpoint**, an **MCP tool**, and **interactive docs** — without writing a single route, decorator, or server config.

```
skills/summarize/
├── models.py    ← define input & output
├── handler.py   ← write your logic
└── skill.toml   ← name, description, tags, timeout
```

That's the whole model. Drop the folder. Run the server. Done.

---

## Install

```bash
uv add harnessapi
```

---

## 60-second start

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

Your skill is now live at three places simultaneously:

| | |
|---|---|
| `POST /skills/summarize` | HTTP endpoint — SSE streaming by default |
| `GET /docs` | Interactive OpenAPI docs |
| `http://localhost:8000/mcp` | MCP server — ready for Claude, Cursor, Copilot |

---

## Streaming — just use `yield`

Return a value for a single response. Use `yield` to stream chunks as they're produced. Same endpoint, no extra config.

```python
# One-shot
async def handle(input: Input) -> Output:
    return Output(result=compute(input))

# Streaming
async def handle(input: Input):
    async for token in llm.stream(input.prompt):
        yield token
```

Clients receive standard Server-Sent Events:

```
event: chunk
data: The answer is

event: chunk
data: 42.

event: done
data:
```

Want plain JSON? Add `Accept: application/json`. Same endpoint, same code — harnessapi collects the chunks and returns them together.

---

## Every skill is an MCP tool

Connect any MCP client in seconds:

```json
{
  "mcpServers": {
    "my-skills": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Every skill you add is automatically registered as a tool. Add a folder, restart — it appears. No registration code. No schema maintenance.

---

## Scaffold in one command

```bash
# New project with a sample skill
harnessapi init my-project

# Add API layer to an existing agentskills.io skill
harnessapi init --skill .agents/skills/summarize

# Convert a whole skills directory
harnessapi init --skills-dir .agents/skills

# Wrap a plain Python function as a skill
harnessapi init --function utils/compute.py --output skills
```

harnessapi is a compatible superset of the [agentskills.io](https://agentskills.io) standard — your existing skill folders work as-is.

---

## See it live: streaming factorial

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

Patch a skill without restarting the server:

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

## What you get

| | |
|---|---|
| HTTP endpoint | `POST /skills/{name}` for every skill, automatically |
| Streaming | SSE by default · JSON via `Accept: application/json` |
| MCP server | `/mcp` · all skills auto-registered as tools |
| OpenAPI docs | `/docs` · full Swagger UI, no extra setup |
| Validation | Pydantic — invalid input is rejected before your code runs |
| Timeouts | Per-skill `timeout_secs` in `skill.toml` |
| Hot-swap | Runtime handler replacement via opt-in edit endpoint |
| agentskills.io | Drop-in compatible — existing skill folders just work |

---

## Philosophy

Most frameworks start with routes. Most agent frameworks start with tools. `harnessapi` starts with **skills** — the capability itself. The API and the MCP tool are consequences, not configuration.

Write the thing. Everything else follows.

---

<div align="center">

Built on [FastAPI](https://fastapi.tiangolo.com) · [FastMCP](https://github.com/jlowin/fastmcp) · [Pydantic](https://docs.pydantic.dev) · [uv](https://docs.astral.sh/uv/)

</div>
