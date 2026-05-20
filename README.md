<div align="center">

# harnessapi

**Write a skill. Get an API. Get an MCP tool. Ship.**

[![PyPI version](https://img.shields.io/pypi/v/harnessapi.svg)](https://pypi.org/project/harnessapi/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

You write one Python function. `harnessapi` gives you:

- **A streaming HTTP endpoint** at `POST /skills/{name}` — Server-Sent Events out of the box
- **An MCP tool** at `/mcp` — plug straight into Claude Desktop, Cursor, Copilot, or any agent

No routers. No decorators scattered across files. No separate MCP server to maintain. Just a folder with two files.

---

## Install

```bash
uv add harnessapi
```

---

## 60-second start

```
my_project/
├── main.py
└── skills/
    └── summarize/
        ├── models.py
        └── handler.py
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
"""Summarize text to a target length."""
from .models import Input, Output

async def handle(input: Input) -> Output:
    return Output(summary=input.text[:input.max_length])
```

**`main.py`**
```python
from pathlib import Path
from harnessapi import HarnessAPI

app = HarnessAPI(skills_dir=Path(__file__).parent / "skills")
```

```bash
uvicorn main:app --reload
```

That's it. Your skill is live at `POST /skills/summarize` **and** available as an MCP tool at `http://localhost:8000/mcp`.

---

## Streaming is the default

Return a value → one clean JSON response. Use `yield` → stream chunks to the client as they're produced.

```python
# Non-streaming
async def handle(input: Input) -> Output:
    return Output(result=compute(input))

# Streaming — just yield
async def handle(input: Input):
    async for token in llm.stream(input.prompt):
        yield token
```

Clients get standard Server-Sent Events:

```
event: chunk
data: The answer is

event: chunk
data: 42.

event: done
data:
```

Need plain JSON instead? Add `Accept: application/json` to your request. Same endpoint, no configuration.

---

## Every skill is also an MCP tool

Add `harnessapi` to Claude Desktop in 10 seconds:

```json
{
  "mcpServers": {
    "my-skills": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Every skill you define automatically appears as a tool your agent can call. Add a skill folder, restart the server — it's there.

---

## Try it: streaming factorial

Clone the repo and run the built-in example:

```bash
git clone https://github.com/edwinjosechittilappilly/harnessapi
cd harnessapi
uv sync
uv run uvicorn examples.factorial_app.main:app --reload
```

Watch 5! computed step-by-step over SSE:

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

Or get it all at once:

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
    ├── handler.py        # required — your logic lives here
    ├── models.py         # required — Pydantic Input + Output
    ├── skill.toml        # optional — name, description, tags, timeout
    ├── defaults/
    │   └── input.json    # optional — shown as example in /docs
    └── examples/
        └── 01.json       # optional — {input, output} pairs for docs
```

**`skill.toml`**
```toml
[skill]
description  = "What this skill does"
is_mcp       = true      # default: true — set false to hide from MCP
tags         = ["nlp"]
timeout_secs = 30
```

---

## Prefer decorators? That works too.

```python
from harnessapi import HarnessAPI, SkillInput, SkillOutput, skill

class TranslateInput(SkillInput):
    text: str
    target_lang: str = "es"

class TranslateOutput(SkillOutput):
    translated: str

@skill(name="translate", input_model=TranslateInput, output_model=TranslateOutput)
async def translate(input: TranslateInput) -> TranslateOutput:
    # call your translation API here
    return TranslateOutput(translated=f"[{input.target_lang}] {input.text}")

app = HarnessAPI(title="My Skills")
```

---

## Hot-swap handlers at runtime

Need to tweak a skill without restarting? Enable the edit endpoint and push new code over HTTP:

```python
app = HarnessAPI(skills_dir="./skills", enable_edit_endpoints=True)
```

```bash
curl -X POST http://localhost:8000/skills/summarize/edit \
  -H "Content-Type: application/json" \
  -d '{"source_code": "async def handle(input):\n    return Output(summary=input.text.upper())", "persist": true}'
```

> Disabled by default. Protect with auth middleware before exposing in production.

---

## What you get out of the box

| Feature | Details |
|---|---|
| HTTP endpoint | `POST /skills/{name}` for every skill |
| Streaming | SSE by default, JSON fallback via `Accept` header |
| MCP server | `/mcp` — all skills auto-registered as tools |
| OpenAPI docs | `/docs` — full interactive Swagger UI |
| Pydantic validation | Input validated before your handler is called |
| Timeouts | Per-skill `timeout_secs` in `skill.toml` |
| Hot-swap | Opt-in edit endpoint for runtime handler replacement |

---

## Philosophy

Most API frameworks start with routes. Most agent frameworks start with tools. `harnessapi` starts with **skills** — self-contained units of capability that are both, automatically.

Drop a folder. Define input and output. Everything else is handled.

---

<div align="center">

Built on [FastAPI](https://fastapi.tiangolo.com) · [FastMCP](https://github.com/jlowin/fastmcp) · [Pydantic](https://docs.pydantic.dev) · [uv](https://docs.astral.sh/uv/)

</div>
