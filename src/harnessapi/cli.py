"""harnessapi CLI — scaffold and run harnessapi projects."""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Scaffolded file templates
# ---------------------------------------------------------------------------

_MAIN_PY = '''\
from pathlib import Path
from harnessapi import HarnessAPI

app = HarnessAPI(
    skills_dir=Path(__file__).parent / "skills",
    title="{title}",
    description="Powered by harnessapi",
)
'''

_MODELS_PY = '''\
from harnessapi import SkillInput, SkillOutput


class Input(SkillInput):
    name: str


class Output(SkillOutput):
    message: str
    length: int
'''

_HANDLER_PY = '''\
"""Greet someone by name."""
from .models import Input, Output


async def handle(input: Input) -> Output:
    message = f"Hello, {input.name}! Welcome to harnessapi."
    return Output(message=message, length=len(message))
'''

_SKILL_TOML = '''\
[skill]
description  = "Greet someone by name"
is_mcp       = true
tags         = ["demo"]
timeout_secs = 30
'''

_DEFAULTS_JSON = '''\
{"name": "world"}
'''

_EXAMPLES_JSON = '''\
{
  "input":  {"name": "Edwin"},
  "output": {"message": "Hello, Edwin! Welcome to harnessapi.", "length": 38}
}
'''

_GITIGNORE = '''\
__pycache__/
*.py[cod]
.venv/
dist/
.env
'''

_README = '''\
# {title}

Built with [harnessapi](https://github.com/edwinjosechittilappilly/harnessapi).

## Run

```bash
harnessapi run
```

## Call the greet skill

```bash
# SSE stream (default)
curl -X POST http://localhost:8000/skills/greet \\
  -H "Content-Type: application/json" \\
  -d \'{{"name": "world"}}\\'

# Plain JSON
curl -X POST http://localhost:8000/skills/greet \\
  -H "Content-Type: application/json" \\
  -H "Accept: application/json" \\
  -d \'{{"name": "world"}}\\'
```

## MCP

Connect any MCP client to `http://localhost:8000/mcp`.
'''


# ---------------------------------------------------------------------------
# Scaffold logic
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"  created  {path}")


def init(project_name: str | None = None) -> None:
    """Scaffold a new harnessapi project in the current directory."""
    cwd = Path.cwd()

    # Determine project name
    if project_name is None:
        project_name = cwd.name

    # Detect if we're scaffolding into a blank dir or a named sub-dir
    target = cwd
    is_empty = not any(p for p in target.iterdir() if not p.name.startswith("."))
    if not is_empty:
        # scaffold into a new sub-directory
        target = cwd / project_name
        if target.exists():
            print(f"Error: '{target}' already exists.")
            sys.exit(1)

    title = project_name.replace("-", " ").replace("_", " ").title()

    print(f"\nScaffolding harnessapi project: {project_name}\n")

    _write(target / "main.py",                                    _MAIN_PY.format(title=title))
    _write(target / "skills" / "greet" / "models.py",             _MODELS_PY)
    _write(target / "skills" / "greet" / "handler.py",            _HANDLER_PY)
    _write(target / "skills" / "greet" / "skill.toml",            _SKILL_TOML)
    _write(target / "skills" / "greet" / "defaults" / "input.json", _DEFAULTS_JSON)
    _write(target / "skills" / "greet" / "examples" / "01.json",  _EXAMPLES_JSON)
    _write(target / ".gitignore",                                  _GITIGNORE)
    _write(target / "README.md",                                   _README.format(title=title))

    cd_line = f"  cd {project_name}" if target != cwd else ""
    print(f"""
Done! Next steps:
{cd_line}
  harnessapi run

Then try it:

  curl -X POST http://localhost:8000/skills/greet \\
    -H "Content-Type: application/json" \\
    -d '{{"name": "world"}}'

MCP server:   http://localhost:8000/mcp
OpenAPI docs: http://localhost:8000/docs
""".strip())


# ---------------------------------------------------------------------------
# Run command
# ---------------------------------------------------------------------------

def run(args: list[str]) -> None:
    """Start the harnessapi server — mirrors `uvicorn main:app` with sensible defaults.

    Usage: harnessapi run [--host HOST] [--port PORT] [--no-reload] [--app APP]
    """
    import argparse
    parser = argparse.ArgumentParser(
        prog="harnessapi run",
        description="Start the harnessapi development server.",
    )
    parser.add_argument(
        "--app", default=None,
        help="App to serve as module:attribute (default: auto-detected from main.py or app.py)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument(
        "--no-reload", action="store_true",
        help="Disable auto-reload (default: reload is on)",
    )
    opts = parser.parse_args(args)

    app_str = opts.app or _detect_app()
    if app_str is None:
        print("Error: could not find an app. Create main.py with a HarnessAPI instance,")
        print("       or pass --app module:attribute explicitly.")
        sys.exit(1)

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is not installed. Run: uv add uvicorn")
        sys.exit(1)

    reload = not opts.no_reload
    print(f"Starting harnessapi  →  http://{opts.host}:{opts.port}")
    print(f"  app:     {app_str}")
    print(f"  reload:  {reload}")
    print(f"  docs:    http://{opts.host}:{opts.port}/docs")
    print(f"  mcp:     http://{opts.host}:{opts.port}/mcp")
    print()

    uvicorn.run(
        app_str,
        host=opts.host,
        port=opts.port,
        reload=reload,
    )


def _detect_app() -> str | None:
    """Look for main.py or app.py in cwd and find the HarnessAPI instance inside."""
    cwd = Path.cwd()
    candidates = [("main", "main.py"), ("app", "app.py")]

    # Add cwd to sys.path so the module can be imported
    if str(cwd) not in sys.path:
        sys.path.insert(0, str(cwd))

    for module_name, filename in candidates:
        if not (cwd / filename).exists():
            continue
        # Try to find the attribute name that holds a HarnessAPI instance
        attr = _find_harness_attr(cwd / filename, module_name)
        if attr:
            return f"{module_name}:{attr}"

    return None


def _find_harness_attr(path: Path, module_name: str) -> str | None:
    """Import the file and find the first HarnessAPI attribute, defaulting to 'app'."""
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        # Can't import — fall back to convention
        return "app"

    from harnessapi import HarnessAPI
    for name in dir(mod):
        obj = getattr(mod, name, None)
        if isinstance(obj, HarnessAPI):
            return name

    # Fallback: assume 'app' even if we couldn't confirm
    return "app"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_HELP = """\
Usage: harnessapi <command> [options]

Commands:
  init [project-name]   Scaffold a new harnessapi project
  run                   Start the development server

Options (run):
  --app MODULE:ATTR     App to serve (default: auto-detected)
  --host HOST           Bind host            (default: 127.0.0.1)
  --port PORT           Bind port            (default: 8000)
  --no-reload           Disable auto-reload

Examples:
  harnessapi init my-project
  harnessapi run
  harnessapi run --port 8080 --host 0.0.0.0
"""


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(_HELP)
        sys.exit(0)

    command, rest = args[0], args[1:]

    if command == "init":
        project_name = rest[0] if rest else None
        init(project_name)
    elif command == "run":
        run(rest)
    else:
        print(f"Unknown command: '{command}'")
        print(_HELP)
        sys.exit(1)


if __name__ == "__main__":
    main()
