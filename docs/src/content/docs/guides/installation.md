---
title: Installation
description: Install harnessapi with uv, pip, or try it instantly with uvx. Covers requirements, optional extras, and contributor setup.
---

## Requirements

- Python **3.11 or higher**
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

Python 3.11 is the minimum because harnessapi uses `tomllib` (stdlib, 3.11+) for `skill.toml` parsing and relies on asyncio improvements introduced in 3.11 for reliable streaming and timeout behavior.

---

## Install with uv (recommended)

```bash
uv add harnessapi
```

uv resolves and installs dependencies significantly faster than pip and produces a lockfile automatically. If you don't have uv yet:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Install with pip

```bash
pip install harnessapi
```

---

## Try without installing

Use `uvx` to run harnessapi commands in a temporary isolated environment — no install step, no virtual environment to manage:

```bash
# Scaffold and run a new project
uvx harnessapi init my-project
cd my-project
uvx harnessapi run
```

This is the fastest way to evaluate harnessapi or run it in CI without a persistent install.

---

## Optional extras

Install additional providers for per-tenant sandboxes (only needed if you use the multi-tenancy sandbox feature):

```bash
# Docker sandbox provider
uv add "harnessapi[docker]"

# Kubernetes sandbox provider
uv add "harnessapi[kubernetes]"

# Both
uv add "harnessapi[docker,kubernetes]"
```

The base install (`harnessapi` with no extras) supports `local_subprocess` sandboxes out of the box — no extra deps needed for development.

---

## Verify the install

```bash
harnessapi --help
```

Expected output:

```
Usage: harnessapi [OPTIONS] COMMAND [ARGS]...

  harnessapi — skill-first streaming API and MCP tool framework.

Options:
  --help  Show this message and exit.

Commands:
  init  Scaffold a new harnessapi project or skill.
  run   Start the harnessapi development server.
```

If you see this, the CLI is installed and working.

---

## Install from source (contributors)

```bash
git clone https://github.com/edwinjosechittilappilly/harnessapi
cd harnessapi
uv sync
```

`uv sync` installs the project and all development dependencies from the lockfile. Run the test suite:

```bash
uv run pytest
```

---

## Core dependencies

harnessapi installs these automatically — no manual installation needed:

| Package | Purpose |
|---------|---------|
| `fastapi` | HTTP server, routing, OpenAPI/Swagger |
| `fastmcp` | MCP server and tool registration |
| `pydantic` | Input/output validation |
| `uvicorn` | ASGI server |
| `sse-starlette` | Server-Sent Events streaming |
| `anyio` | Async runtime compatibility |
