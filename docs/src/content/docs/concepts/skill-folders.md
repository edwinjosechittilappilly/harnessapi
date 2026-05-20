---
title: Skill folders
description: Learn about the harnessapi skill folder structure — the core unit of every API endpoint and MCP tool.
---

A **skill folder** is the core building block of harnessapi. Each folder becomes one HTTP endpoint and one MCP tool automatically.

## Minimum structure

```
skills/
└── my-skill/
    ├── handler.py    ← required
    └── models.py     ← required
```

## Full structure

```
skills/
└── my-skill/
    ├── handler.py        ← required: your logic
    ├── models.py         ← required: Pydantic Input + Output
    ├── SKILL.md          ← optional: agentskills.io metadata
    ├── skill.toml        ← optional: name, description, tags, timeout
    ├── defaults/
    │   └── input.json    ← optional: shown as defaults in /docs
    └── examples/
        └── 01.json       ← optional: {input, output} pairs for docs
```

## models.py

Defines your skill's input and output using Pydantic:

```python
from harnessapi import SkillInput, SkillOutput

class Input(SkillInput):
    text: str
    max_length: int = 200   # optional field with default

class Output(SkillOutput):
    summary: str
    word_count: int
```

`SkillInput` extends `BaseModel` with `extra="forbid"` — extra fields are rejected with a 422 before your handler is called.

## handler.py

Contains the `handle` async function — either returning a value (non-streaming) or yielding chunks (streaming):

```python
from .models import Input, Output

# Non-streaming
async def handle(input: Input) -> Output:
    return Output(summary=input.text[:input.max_length], word_count=len(input.text.split()))

# Streaming
async def handle(input: Input):
    for word in input.text.split():
        yield word
```

Relative imports (`from .models import ...`) work out of the box.

## skill.toml

Controls metadata, MCP registration, and timeout:

```toml
[skill]
description  = "Summarize text to a target length"
is_mcp       = true      # set false to hide from MCP clients
tags         = ["text", "nlp"]
timeout_secs = 30        # default: 30
```

If `skill.toml` is absent, harnessapi uses the folder name as the skill name and the handler docstring as the description.

## SKILL.md

Optional [agentskills.io](https://agentskills.io) compatible metadata file. harnessapi reads the YAML frontmatter and Markdown body:

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

`skill.toml` values take priority over `SKILL.md` frontmatter.

## Discovery

harnessapi scans the `skills_dir` at startup. Any subfolder containing `handler.py` and `models.py` is loaded as a skill. Folders with only `SKILL.md` (no handler) are detected but skipped for API exposure — a warning is logged.

```python
from pathlib import Path
from harnessapi import HarnessAPI

app = HarnessAPI(skills_dir=Path(__file__).parent / "skills")
```
