# harnessapi

**Skill-first API framework** — define a skill once, get both an HTTP endpoint and an MCP tool automatically.

Every skill is a folder. Drop in a `handler.py` and `models.py` and you have:
- `POST /skills/{name}` — streaming SSE by default, JSON on request
- An MCP tool at `/mcp` — ready for Claude Desktop, Cursor, or any MCP client

---

## Install

```bash
uv add harnessapi
```

Or clone and run locally:

```bash
git clone <repo>
cd harnessapi
uv sync
```

---

## Quickstart

Create your skill folder:

```
my_project/
├── main.py
└── skills/
    └── greet/
        ├── models.py
        └── handler.py
```

**`skills/greet/models.py`**
```python
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    name: str

class Output(SkillOutput):
    message: str
```

**`skills/greet/handler.py`**
```python
"""Say hello to someone."""
from .models import Input, Output

async def handle(input: Input) -> Output:
    return Output(message=f"Hello, {input.name}!")
```

**`main.py`**
```python
from pathlib import Path
from harnessapi import HarnessAPI

app = HarnessAPI(skills_dir=Path(__file__).parent / "skills")
```

Run it exactly like a FastAPI app:

```bash
uvicorn main:app --reload
```

---

## Try the factorial example

The repo ships with a streaming factorial skill that demonstrates SSE + MCP together.

```bash
# from the repo root
uv run uvicorn examples.factorial_app.main:app --reload
```

### Call via HTTP — SSE stream (default)

```bash
curl -X POST http://localhost:8000/skills/factorial \
  -H "Content-Type: application/json" \
  -d '{"n": 5}'
```

Response (each multiplication step streamed as it's computed):

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

### Call via HTTP — plain JSON

```bash
curl -X POST http://localhost:8000/skills/factorial \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"n": 5}'
```

```json
{"chunks": ["start: 1", "2: 2", "3: 6", "4: 24", "5: 120"]}
```

### Connect an MCP client

The MCP server is automatically available at:

```
http://localhost:8000/mcp
```

Add it to **Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "harnessapi": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Or add it to **Cursor** settings under MCP servers.

The `factorial` skill is automatically registered as an MCP tool with parameter `input.n: int`.

---

## Skill folder structure

```
skills/
└── my_skill/
    ├── handler.py        # REQUIRED — async def handle(input: Input) -> Output
    ├── models.py         # REQUIRED — class Input(SkillInput), class Output(SkillOutput)
    ├── skill.toml        # optional — metadata
    ├── defaults/
    │   └── input.json    # optional — default values shown in OpenAPI docs
    └── examples/
        └── 01.json       # optional — {input: {...}, output: {...}} example pairs
```

**`skill.toml`** (all optional):
```toml
[skill]
description  = "What this skill does"
is_mcp       = true      # expose as MCP tool (default: true)
tags         = ["math"]
timeout_secs = 30
```

### Streaming vs non-streaming

Return a value → non-streaming (single `result` SSE event):
```python
async def handle(input: Input) -> Output:
    return Output(...)
```

Use `yield` → streaming (multiple `chunk` SSE events):
```python
async def handle(input: Input):
    for item in compute_steps(input):
        yield item
```

---

## Decorator API (no folder needed)

```python
from harnessapi import HarnessAPI, SkillInput, SkillOutput, skill

class TranslateInput(SkillInput):
    text: str
    target_lang: str = "es"

class TranslateOutput(SkillOutput):
    translated: str

@skill(
    name="translate",
    input_model=TranslateInput,
    output_model=TranslateOutput,
    is_mcp=True,
)
async def translate_handler(input: TranslateInput) -> TranslateOutput:
    return TranslateOutput(translated=f"[{input.target_lang}] {input.text}")

app = HarnessAPI(title="My Skills")
```

---

## Runtime edit endpoint (advanced)

Enable hot-swapping a skill's handler over HTTP:

```python
app = HarnessAPI(skills_dir="./skills", enable_edit_endpoints=True)
```

```bash
curl -X POST http://localhost:8000/skills/factorial/edit \
  -H "Content-Type: application/json" \
  -d '{
    "source_code": "async def handle(input):\n    yield f\"custom: {input.n}\"",
    "persist": false
  }'
```

> **Security note**: The edit endpoint executes arbitrary Python. Always protect it with authentication middleware in production. It is disabled by default.

---

## SSE event protocol

| Event    | When                                      |
|----------|-------------------------------------------|
| `chunk`  | Each yielded value from a streaming handler |
| `result` | The final output of a non-streaming handler |
| `done`   | Always the last event                     |
| `error`  | Handler raised an exception               |

---

## OpenAPI docs

Interactive docs are available at `http://localhost:8000/docs` — all skills appear as documented POST endpoints with their Pydantic schemas.
