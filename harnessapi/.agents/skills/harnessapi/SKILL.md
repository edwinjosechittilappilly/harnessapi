---
name: harnessapi
description: harnessapi best practices, skill creation, and API exposure. Use when working with harnessapi, creating or editing skill folders, converting agentskills.io skills to API endpoints, wrapping Python functions as skills, running the skill server, or connecting MCP clients. Keeps harnessapi code idiomatic and up to date.
---

## Overview

harnessapi is a skill-first API framework. A **skill** is a folder — it is simultaneously an agentskills.io-compatible skill, an HTTP endpoint, and an MCP tool. You define it once; harnessapi exposes it everywhere.

## Skill folder structure

Every skill folder is a superset of the agentskills.io standard:

```
skills/
└── my-skill/
    ├── SKILL.md        # agentskills.io standard — REQUIRED for full compatibility
    ├── handler.py      # harnessapi — REQUIRED for API exposure
    ├── models.py       # harnessapi — REQUIRED for API exposure
    ├── skill.toml      # harnessapi — optional, overrides SKILL.md metadata
    ├── scripts/        # agentskills.io optional
    ├── references/     # agentskills.io optional
    ├── assets/         # agentskills.io optional
    ├── defaults/
    │   └── input.json  # harnessapi optional — default shown in /docs
    └── examples/
        └── 01.json     # harnessapi optional — {input, output} pairs
```

- A folder with only `SKILL.md` is a valid agentskills.io skill (read by agents).
- A folder with `SKILL.md` + `handler.py` + `models.py` is a full harnessapi skill (API + MCP).

## SKILL.md format

```markdown
---
name: my-skill
description: What this skill does. Use when asked to <trigger phrases>.
license: MIT
compatibility: Python 3.11+
---

Instructions for the agent...
```

`name` must match the folder name exactly (lowercase, hyphens).

## models.py

```python
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    text: str
    max_length: int = 200

class Output(SkillOutput):
    result: str
```

- Always subclass `SkillInput` and `SkillOutput`.
- `extra="forbid"` is set by default — no extra fields pass validation.

## handler.py — non-streaming

```python
"""One-line description used as MCP tool description."""
from .models import Input, Output

async def handle(input: Input) -> Output:
    return Output(result=input.text[:input.max_length])
```

## handler.py — streaming (use `yield`)

```python
"""Stream results token by token."""
from .models import Input

async def handle(input: Input):   # no return type — async generator
    for word in input.text.split():
        yield word + " "
```

Streaming handlers yield chunks as SSE `chunk` events. Non-streaming handlers emit a single `result` event.

## HarnessAPI app

```python
from pathlib import Path
from harnessapi import HarnessAPI

app = HarnessAPI(
    skills_dir=Path(__file__).parent / "skills",
    title="My App",
)
```

Run like any FastAPI app: `harnessapi run` or `uvicorn main:app --reload`.

## skill.toml (optional)

```toml
[skill]
description  = "What this skill does"
is_mcp       = true       # expose as MCP tool (default: true)
tags         = ["nlp"]
timeout_secs = 30
license      = "MIT"
```

Values in `skill.toml` override `SKILL.md` frontmatter.

## init commands

Read `references/init-commands.md` when creating, converting, or scaffolding skills.

## Streaming and SSE

Read `references/streaming.md` when implementing streaming handlers or calling skill endpoints.

## MCP integration

Read `references/mcp.md` when connecting MCP clients or debugging tool registration.

## Skill structure details

Read `references/skill-structure.md` for the full file-by-file reference.
