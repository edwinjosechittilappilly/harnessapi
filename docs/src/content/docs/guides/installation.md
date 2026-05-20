---
title: Installation
description: Install harnessapi with uv, pip, or try it instantly with uvx.
---

## Requirements

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Install with uv

```bash
uv add harnessapi
```

## Install with pip

```bash
pip install harnessapi
```

## Try without installing

Use `uvx` to run harnessapi commands in a temporary isolated environment — no install step needed:

```bash
uvx harnessapi init my-project
uvx harnessapi run
```

## Verify

```bash
harnessapi --help
```

## Dependencies

harnessapi installs these automatically:

| Package | Purpose |
|---------|---------|
| `fastapi` | HTTP server and routing |
| `fastmcp` | MCP server |
| `pydantic` | Input/output validation |
| `uvicorn` | ASGI server |
| `sse-starlette` | Server-Sent Events |
| `anyio` | Async runtime |
