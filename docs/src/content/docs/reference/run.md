---
title: harnessapi run
description: Reference for the harnessapi run CLI command — start the development server with auto-reload.
---

Starts the harnessapi development server using uvicorn with auto-reload enabled.

## Usage

```bash
harnessapi run [options]
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--app MODULE:ATTR` | auto-detected | App to serve (e.g. `main:app`) |
| `--host HOST` | `127.0.0.1` | Bind host |
| `--port PORT` | `8000` | Bind port |
| `--no-reload` | — | Disable auto-reload |

## Auto-detection

If `--app` is not specified, harnessapi scans the current directory for `main.py` or `app.py` and finds the `HarnessAPI` instance automatically.

## Examples

```bash
# Default — auto-detects main:app, port 8000, with reload
harnessapi run

# Custom port
harnessapi run --port 8080

# Expose to network
harnessapi run --host 0.0.0.0 --port 8000

# Production (no reload)
harnessapi run --no-reload

# Explicit app
harnessapi run --app mymodule:app
```

## URLs when running

| URL | What |
|-----|------|
| `http://localhost:8000/skills/{name}` | Skill HTTP endpoints |
| `http://localhost:8000/docs` | Swagger UI |
| `http://localhost:8000/redoc` | ReDoc |
| `http://localhost:8000/mcp` | MCP server |
| `http://localhost:8000/openapi.json` | OpenAPI schema |

## Production deployment

For production, use uvicorn or gunicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

See [Deploy to production](/guides/deploy/) for full guidance.
