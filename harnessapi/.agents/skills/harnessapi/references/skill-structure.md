# Skill folder structure reference

## Full structure

```
skills/
└── my-skill/
    ├── SKILL.md                  # agentskills.io required
    ├── handler.py                # harnessapi required
    ├── models.py                 # harnessapi required
    ├── skill.toml                # harnessapi optional
    ├── scripts/                  # agentskills.io optional
    ├── references/               # agentskills.io optional
    ├── assets/                   # agentskills.io optional
    ├── defaults/
    │   └── input.json            # harnessapi optional
    ├── examples/
    │   └── 01.json               # harnessapi optional
    └── edit/
        └── handler.py            # harnessapi optional (hot-swap)
```

## SKILL.md frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Matches folder name, lowercase-hyphen |
| `description` | Yes | What it does + "Use when..." trigger phrase |
| `license` | No | SPDX identifier e.g. `MIT` |
| `compatibility` | No | e.g. `Python 3.11+` |
| `allowed-tools` | No | Space-separated tool whitelist |
| `argument-hint` | No | Prompt hint for the user |

## handler.py

Must export `handle`. Either:
- `async def handle(input: Input) -> Output` — non-streaming
- `async def handle(input: Input)` with `yield` — streaming

The module docstring is used as the MCP tool description if no `skill.toml` or `SKILL.md` description is provided.

## models.py

Must export `Input(SkillInput)` and `Output(SkillOutput)`. Both use Pydantic v2.

`extra="forbid"` is set on base classes — unknown fields raise validation errors.

## skill.toml

```toml
[skill]
name         = "my-skill"       # default: folder name
description  = "..."            # default: SKILL.md description or handler docstring
is_mcp       = true             # default: true
tags         = ["category"]     # default: []
timeout_secs = 30               # default: 30.0
license      = "MIT"            # default: none
compatibility = "Python 3.11+"  # default: none
```

Values override SKILL.md frontmatter. Priority: `skill.toml` > `SKILL.md` > folder name / docstring.

## defaults/input.json

Shown in `/docs` as the example request body. Must match the `Input` schema.

```json
{"field": "value"}
```

## examples/01.json

Input/output pair for documentation:

```json
{
  "input":  {"field": "value"},
  "output": {"result": "expected"}
}
```

Multiple examples: `01.json`, `02.json`, etc. — loaded in sorted order.

## edit/handler.py

Optional hot-swap handler. If present at startup, loaded in place of `handler.py`. Can also be pushed via:

```bash
# Only available when enable_edit_endpoints=True
curl -X POST http://localhost:8000/skills/my-skill/edit \
  -H "Content-Type: application/json" \
  -d '{"source_code": "async def handle(input):\n    ...", "persist": true}'
```

## agentskills.io compatibility

A folder with only `SKILL.md` is a valid agentskills.io skill. harnessapi will warn (not error) and skip it for API exposure. Use `harnessapi init --skill <path>` to add the API layer.

The default discovery root is whatever is passed to `skills_dir=`. The agentskills.io default is `.agents/skills/` — point `skills_dir` there if you follow that convention.
