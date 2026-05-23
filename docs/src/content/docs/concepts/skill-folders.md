---
title: Skill folders
description: The complete reference for harnessapi skill folders — the core unit that becomes an HTTP endpoint, MCP tool, and Swagger entry automatically.
---

A **skill folder** is the fundamental building block of harnessapi. Each folder is a self-contained capability: it declares its inputs and outputs, implements its logic, and optionally configures metadata. harnessapi discovers it at startup and exposes it as an HTTP endpoint, an MCP tool, and a Swagger entry — no additional code required.

---

## Discovery lifecycle

When `HarnessAPI` starts, it scans `skills_dir` and for every subfolder containing both `handler.py` and `models.py`:

1. Imports `models.py` and validates that `Input` and `Output` classes exist
2. Imports `handler.py` and locates the `handle` async function
3. Reads `skill.toml` (or `SKILL.md`) for metadata — name, description, tags, timeout
4. Registers `POST /skills/{name}` as an HTTP endpoint (SSE streaming by default)
5. Registers `{name}` as a FastMCP tool at `/mcp`
6. Adds the skill to the OpenAPI schema at `/docs`

Folders missing either required file are skipped with a warning. No restart is needed when you add a new skill — just restart the server.

---

## Skill naming

The skill name is derived from the folder name by default. harnessapi uses the folder name as-is for the URL slug:

| Folder name | HTTP endpoint | MCP tool name |
|---|---|---|
| `greet` | `POST /skills/greet` | `greet` |
| `summarize-text` | `POST /skills/summarize-text` | `summarize-text` |
| `image_caption` | `POST /skills/image_caption` | `image_caption` |

Override the name in `skill.toml`:

```toml
[skill]
name = "summarize"   # overrides the folder name
```

---

## Minimum structure

```
skills/
└── my-skill/
    ├── handler.py    ← required
    └── models.py     ← required
```

---

## Full structure

```
skills/
└── my-skill/
    ├── handler.py        ← required: async handle() function
    ├── models.py         ← required: Pydantic Input + Output
    ├── skill.toml        ← optional: name, description, tags, timeout
    ├── SKILL.md          ← optional: agentskills.io compatible metadata
    ├── defaults/
    │   └── input.json    ← optional: default values shown in /docs
    └── examples/
        └── 01.json       ← optional: {input, output} pairs for /docs
```

---

## models.py

Defines the skill's input and output using Pydantic:

```python
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    text: str
    max_length: int = 200          # optional field with default
    include_word_count: bool = False

class Output(SkillOutput):
    summary: str
    word_count: int | None = None
```

**`SkillInput`** extends `BaseModel` with `extra="forbid"` — any unrecognized field in the request body returns a `422 Unprocessable Entity` before your handler is called:

```json
{
  "detail": [
    {
      "type": "extra_forbidden",
      "loc": ["body", "unknown_field"],
      "msg": "Extra inputs are not permitted"
    }
  ]
}
```

This makes your skill's contract explicit: callers know exactly which fields are accepted. Use `Optional` fields with defaults for parameters that are not always required.

**Nested models** work exactly as in Pydantic:

```python
class Metadata(BaseModel):
    author: str
    language: str = "en"

class Input(SkillInput):
    text: str
    metadata: Metadata | None = None
```

---

## handler.py

Contains the `handle` async function — either returning a value (non-streaming) or yielding chunks (streaming):

```python
from .models import Input, Output

# Non-streaming — return a single Output
async def handle(input: Input) -> Output:
    summary = input.text[:input.max_length]
    count = len(input.text.split()) if input.include_word_count else None
    return Output(summary=summary, word_count=count)

# Streaming — yield chunks progressively
async def handle(input: Input):
    words = input.text.split()
    for word in words:
        yield word + " "
```

Handlers are always `async`. Relative imports from other files in the same folder work out of the box.

---

## Multi-file handlers

For larger skills, split logic across multiple files in the folder:

```
skills/summarize/
├── handler.py
├── models.py
├── chunker.py     ← helper module
└── prompts.py     ← prompt templates
```

```python title="skills/summarize/handler.py"
from .models import Input, Output
from .chunker import split_into_chunks
from .prompts import SUMMARIZE_PROMPT

async def handle(input: Input) -> Output:
    chunks = split_into_chunks(input.text, size=500)
    summary = await summarize_chunks(chunks, SUMMARIZE_PROMPT)
    return Output(summary=summary)
```

The entire folder is a Python package — any standard import pattern works.

---

## skill.toml

Controls metadata, MCP visibility, and timeout:

```toml
[skill]
name         = "summarize"          # optional: overrides folder name
description  = "Summarize text to a target length"
is_mcp       = true                 # set false to hide from MCP clients
tags         = ["text", "nlp"]
timeout_secs = 30                   # default: 30
```

If `skill.toml` is absent, harnessapi uses the folder name as the skill name and the `handle` docstring (if present) as the description.

---

## SKILL.md

Optional [agentskills.io](https://agentskills.io) compatible metadata file. harnessapi reads the YAML frontmatter:

```markdown
---
name: summarize
description: Summarize text to a target length. Use when asked to shorten or condense text.
license: MIT
compatibility: Python 3.11+
argument-hint: The text to summarize
---

Summarizes the input text by truncating to the specified maximum length.
```

`skill.toml` values take priority over `SKILL.md` frontmatter when both are present.

---

## defaults/input.json

Populates the Swagger UI "Try it out" form with realistic default values:

```json title="skills/summarize/defaults/input.json"
{
  "text": "Python is a high-level, general-purpose programming language...",
  "max_length": 100,
  "include_word_count": true
}
```

These values appear pre-filled when a user opens `/docs` and clicks "Try it out" for the skill. They do not affect runtime behavior.

---

## examples/01.json

Provides input/output example pairs shown in the Swagger schema:

```json title="skills/summarize/examples/01.json"
{
  "input": {
    "text": "Python is a high-level programming language.",
    "max_length": 20
  },
  "output": {
    "summary": "Python is a high-lev",
    "word_count": null
  }
}
```

Additional examples follow the same pattern: `02.json`, `03.json`, etc.

---

## Multiple skills

A real project with several skills:

```
skills/
├── greet/
│   ├── handler.py
│   ├── models.py
│   └── skill.toml
├── summarize/
│   ├── handler.py
│   ├── models.py
│   ├── chunker.py
│   └── skill.toml
└── translate/
    ├── handler.py
    ├── models.py
    └── skill.toml
```

Each folder becomes its own endpoint and MCP tool independently. Adding a folder, restarting the server, and the skill is live — no route registration, no tool configuration.

---

## See also

- [Streaming (SSE)](/harnessapi/concepts/streaming) — return vs yield, SSE event format, timeout handling
- [MCP tools](/harnessapi/concepts/mcp) — how Input models become MCP tool schemas
- [Quick start](/harnessapi/guides/quickstart) — build your first skill end-to-end
