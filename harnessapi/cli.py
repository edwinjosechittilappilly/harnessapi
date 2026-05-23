"""harnessapi CLI — scaffold, convert, and run harnessapi projects."""
from __future__ import annotations

import ast
import importlib
import importlib.resources
import importlib.util
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Scaffolded file templates (default init)
# ---------------------------------------------------------------------------

_SKILL_MD = '''\
---
name: {name}
description: {description}
---

{instructions}
'''

_MAIN_PY = '''\
from pathlib import Path
from harnessapi import HarnessAPI

app = HarnessAPI(
    skills_dir=Path(__file__).parent / "skills",
    title="{title}",
    description="Powered by harnessapi",
)
'''

_MODELS_PY_DEFAULT = '''\
from harnessapi import SkillInput, SkillOutput


class Input(SkillInput):
    name: str


class Output(SkillOutput):
    message: str
    length: int
'''

_HANDLER_PY_DEFAULT = '''\
"""Greet someone by name."""
from .models import Input, Output


async def handle(input: Input) -> Output:
    message = f"Hello, {input.name}! Welcome to harnessapi."
    return Output(message=message, length=len(message))
'''

_SKILL_TOML_DEFAULT = '''\
[skill]
description  = "Greet someone by name"
is_mcp       = true
tags         = ["demo"]
timeout_secs = 30
'''

_MODELS_PY_STUB = '''\
from harnessapi import SkillInput, SkillOutput


# TODO: define your input fields based on the skill's SKILL.md
class Input(SkillInput):
    pass


# TODO: define your output fields
class Output(SkillOutput):
    pass
'''

_HANDLER_PY_STUB = '''\
"""{description}"""
from .models import Input, Output


async def handle(input: Input) -> Output:
    # TODO: implement skill logic
    raise NotImplementedError
'''

_SKILL_TOML_STUB = '''\
[skill]
description  = "{description}"
is_mcp       = true
tags         = []
timeout_secs = 30
'''

_DEFAULTS_JSON = '{"name": "world"}'

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
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"  created  {path}")


def _skip(path: Path) -> None:
    print(f"  exists   {path}  (skipped)")


def _write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        _skip(path)
    else:
        _write(path, content)


# ---------------------------------------------------------------------------
# Default scaffold (harnessapi init [name])
# ---------------------------------------------------------------------------

def init_project(project_name: str | None = None) -> None:
    cwd = Path.cwd()
    if project_name is None:
        project_name = cwd.name

    target = cwd
    is_empty = not any(p for p in target.iterdir() if not p.name.startswith("."))
    if not is_empty:
        target = cwd / project_name
        if target.exists():
            print(f"Error: '{target}' already exists.")
            sys.exit(1)

    title = project_name.replace("-", " ").replace("_", " ").title()
    print(f"\nScaffolding harnessapi project: {project_name}\n")

    skill_dir = target / "skills" / "greet"
    _write(target / "main.py",                   _MAIN_PY.format(title=title))
    _write(skill_dir / "SKILL.md",               _SKILL_MD.format(
        name="greet",
        description="Greet someone by name. Use when asked to greet, say hello, or welcome someone.",
        instructions="Say hello using the provided name and return the message with its length.",
    ))
    _write(skill_dir / "models.py",              _MODELS_PY_DEFAULT)
    _write(skill_dir / "handler.py",             _HANDLER_PY_DEFAULT)
    _write(skill_dir / "skill.toml",             _SKILL_TOML_DEFAULT)
    _write(skill_dir / "defaults" / "input.json", _DEFAULTS_JSON)
    _write(skill_dir / "examples" / "01.json",   _EXAMPLES_JSON)
    _write(target / ".gitignore",                _GITIGNORE)
    _write(target / "README.md",                 _README.format(title=title))

    cd_line = f"\n  cd {project_name}" if target != cwd else ""
    print(f"""
Done! Next steps:{cd_line}
  harnessapi run

Then try it:

  curl -X POST http://localhost:8000/skills/greet \\
    -H "Content-Type: application/json" \\
    -d '{{"name": "world"}}'

MCP server:   http://localhost:8000/mcp
OpenAPI docs: http://localhost:8000/docs
""".strip())


# ---------------------------------------------------------------------------
# --skill: add harnessapi layer to an existing agentskills.io skill folder
# ---------------------------------------------------------------------------

def init_skill(skill_path: str) -> None:
    from .skillcompat import parse_skill_md

    folder = Path(skill_path).resolve()
    if not folder.is_dir():
        print(f"Error: '{folder}' is not a directory.")
        sys.exit(1)

    skill_md = folder / "SKILL.md"
    if not skill_md.exists():
        print(f"Error: '{folder}' has no SKILL.md — not a valid agentskills.io skill folder.")
        sys.exit(1)

    md_data, _ = parse_skill_md(skill_md)
    name = md_data.get("name", folder.name)
    description = md_data.get("description", f"Skill: {name}")

    print(f"\nAdding harnessapi layer to skill: {name}\n")

    _write_if_missing(folder / "models.py",  _MODELS_PY_STUB)
    _write_if_missing(folder / "handler.py", _HANDLER_PY_STUB.format(description=description))
    _write_if_missing(folder / "skill.toml", _SKILL_TOML_STUB.format(description=description))

    # Generate main.py one level up from the skill folder
    skills_dir = folder.parent
    main_py = skills_dir.parent / "main.py"
    _write_if_missing(main_py, _MAIN_PY.format(title=name.replace("-", " ").title()))

    print(f"""
Done! Edit handler.py and models.py to implement your skill, then:

  harnessapi run

Docs: http://localhost:8000/docs
MCP:  http://localhost:8000/mcp
""".strip())


# ---------------------------------------------------------------------------
# --skills-dir: add harnessapi layer to all skills in a directory
# ---------------------------------------------------------------------------

def init_skills_dir(skills_dir_path: str) -> None:
    from .skillcompat import parse_skill_md

    skills_dir = Path(skills_dir_path).resolve()
    if not skills_dir.is_dir():
        print(f"Error: '{skills_dir}' is not a directory.")
        sys.exit(1)

    skill_folders = sorted(
        f for f in skills_dir.iterdir()
        if f.is_dir() and not f.name.startswith("_") and (f / "SKILL.md").exists()
    )

    if not skill_folders:
        print(f"No agentskills.io skill folders (with SKILL.md) found in '{skills_dir}'.")
        sys.exit(1)

    print(f"\nAdding harnessapi layer to {len(skill_folders)} skill(s) in: {skills_dir}\n")

    for folder in skill_folders:
        md_data, _ = parse_skill_md(folder / "SKILL.md")
        name = md_data.get("name", folder.name)
        description = md_data.get("description", f"Skill: {name}")
        print(f"  skill: {name}")
        _write_if_missing(folder / "models.py",  _MODELS_PY_STUB)
        _write_if_missing(folder / "handler.py", _HANDLER_PY_STUB.format(description=description))
        _write_if_missing(folder / "skill.toml", _SKILL_TOML_STUB.format(description=description))

    # Generate one main.py pointing at the skills directory
    main_py = skills_dir.parent / "main.py"
    main_content = (
        "from pathlib import Path\n"
        "from harnessapi import HarnessAPI\n\n"
        "app = HarnessAPI(\n"
        f'    skills_dir=Path(__file__).parent / "{skills_dir.name}",\n'
        '    title="My Harness App",\n'
        '    description="Powered by harnessapi",\n'
        ")\n"
    )
    _write_if_missing(main_py, main_content)

    print(f"""
Done! Implement each skill's handler.py and models.py, then:

  harnessapi run

Docs: http://localhost:8000/docs
MCP:  http://localhost:8000/mcp
""".strip())


# ---------------------------------------------------------------------------
# --function: wrap a Python function as a full skill
# ---------------------------------------------------------------------------

def init_function(function_path: str, output_dir: str | None = None) -> None:
    src_path = Path(function_path).resolve()
    if not src_path.exists():
        print(f"Error: '{src_path}' not found.")
        sys.exit(1)

    try:
        tree = ast.parse(src_path.read_text())
    except SyntaxError as e:
        print(f"Error: cannot parse '{src_path}': {e}")
        sys.exit(1)

    # Find all top-level function definitions
    funcs = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.col_offset == 0  # top-level only
    ]

    if not funcs:
        print(f"Error: no top-level functions found in '{src_path}'.")
        sys.exit(1)

    if len(funcs) == 1:
        fn = funcs[0]
    else:
        print(f"Multiple functions found in '{src_path}':")
        for i, f in enumerate(funcs):
            print(f"  [{i}] {f.name}")
        choice = input("Which function to wrap? [0]: ").strip() or "0"
        fn = funcs[int(choice)]

    fn_name = fn.name
    skill_name = fn_name.replace("_", "-")
    docstring = ast.get_docstring(fn) or f"Run {fn_name}"

    # Build Pydantic field stubs from function arguments
    args = fn.args
    input_fields = []
    for arg in args.args:
        if arg.arg in ("self", "cls"):
            continue
        ann = ast.unparse(arg.annotation) if arg.annotation else "str"
        input_fields.append(f"    {arg.arg}: {ann}")

    input_body = "\n".join(input_fields) if input_fields else "    pass  # TODO: add input fields"

    # Build relative import path for the original function
    rel_import = src_path.stem

    models_py = (
        "from harnessapi import SkillInput, SkillOutput\n\n\n"
        f"class Input(SkillInput):\n{input_body}\n\n\n"
        "class Output(SkillOutput):\n"
        "    result: str  # TODO: define output fields\n"
    )

    is_async = isinstance(fn, ast.AsyncFunctionDef)
    await_kw = "await " if is_async else ""
    async_kw = "async " if is_async else ""
    handler_py = (
        f'"""{docstring}"""\n'
        f"import sys\n"
        f"from pathlib import Path\n"
        f"sys.path.insert(0, str(Path(__file__).parent.parent.parent))\n"
        f"from {rel_import} import {fn_name}\n"
        f"from .models import Input, Output\n\n\n"
        f"{async_kw}def handle(input: Input) -> Output:\n"
        f"    result = {await_kw}{fn_name}("
        + ", ".join(f"input.{a.arg}" for a in args.args if a.arg not in ("self", "cls"))
        + ")\n"
        f"    return Output(result=str(result))\n"
    )

    skill_md_content = _SKILL_MD.format(
        name=skill_name,
        description=f"{docstring}. Use when asked to {fn_name.replace('_', ' ')}.",
        instructions=f"Calls `{fn_name}` from `{src_path.name}` and returns the result.",
    )

    skill_toml = _SKILL_TOML_STUB.format(description=docstring)

    out_base = Path(output_dir).resolve() if output_dir else Path.cwd() / "skills"
    skill_dir = out_base / skill_name

    print(f"\nWrapping function '{fn_name}' as skill: {skill_name}\n")

    _write(skill_dir / "SKILL.md",    skill_md_content)
    _write(skill_dir / "models.py",   models_py)
    _write(skill_dir / "handler.py",  handler_py)
    _write(skill_dir / "skill.toml",  skill_toml)

    main_py = out_base.parent / "main.py"
    _write_if_missing(main_py, _MAIN_PY.format(title=skill_name.replace("-", " ").title()))

    print(f"""
Done! Review handler.py and models.py, then:

  harnessapi run

Skill endpoint: POST http://localhost:8000/skills/{skill_name}
MCP tool:       {skill_name}
""".strip())


# ---------------------------------------------------------------------------
# Run command
# ---------------------------------------------------------------------------

def run(args: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog="harnessapi run",
        description="Start the harnessapi development server.",
    )
    parser.add_argument("--app", default=None, help="App as module:attribute (auto-detected)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload")
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

    uvicorn.run(app_str, host=opts.host, port=opts.port, reload=reload)


def _detect_app() -> str | None:
    cwd = Path.cwd()
    if str(cwd) not in sys.path:
        sys.path.insert(0, str(cwd))
    for module_name, filename in [("main", "main.py"), ("app", "app.py")]:
        if (cwd / filename).exists():
            attr = _find_harness_attr(cwd / filename, module_name)
            if attr:
                return f"{module_name}:{attr}"
    return None


def _find_harness_attr(path: Path, module_name: str) -> str | None:
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return "app"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        from harnessapi import HarnessAPI
        for name in dir(mod):
            if isinstance(getattr(mod, name, None), HarnessAPI):
                return name
    except Exception:
        pass
    return "app"


# ---------------------------------------------------------------------------
# examples command — scaffold bundled example projects
# ---------------------------------------------------------------------------

_EXAMPLES = {
    "agentic-rag": "Per-tenant document ingestion and semantic search (ChromaDB + GPT-4o)",
}


def _scaffold_example(name: str, target_dir: Path) -> None:
    if target_dir.exists():
        print(f"Error: '{target_dir}' already exists.")
        sys.exit(1)

    pkg = importlib.resources.files("harnessapi") / "examples" / name
    # importlib.resources.as_file gives a real filesystem path even from a zip wheel
    with importlib.resources.as_file(pkg) as src:
        shutil.copytree(src, target_dir)

    # Print each file so the output matches `init` UX
    for f in sorted(target_dir.rglob("*")):
        if f.is_file():
            print(f"  created  {f.relative_to(target_dir.parent)}")

    print(f"""
Done! Next steps:

  cd {target_dir.name}
  cp .env.example .env        # add your OPENAI_API_KEY
  uv sync
  harnessapi run

Then call your first skill:

  curl -X POST http://localhost:8000/skills/ingest \\
    -H "Content-Type: application/json" \\
    -H "Accept: application/json" \\
    -H "X-Tenant-ID: tenant-1" \\
    -d '{{"text": "Apollo 11 landed on the Moon on July 20, 1969.", "doc_id": "apollo"}}'

  curl -X POST http://localhost:8000/skills/search \\
    -H "Content-Type: application/json" \\
    -H "Accept: application/json" \\
    -H "X-Tenant-ID: tenant-1" \\
    -d '{{"query": "When did Apollo 11 land?"}}'

MCP server:   http://localhost:8000/mcp
Admin MCP:    http://localhost:8000/admin-mcp  (X-Admin-Key: dev-secret)
OpenAPI docs: http://localhost:8000/docs
""".strip())


_EXAMPLE_SCAFFOLD = {
    "agentic-rag": lambda target_dir: _scaffold_example("agentic-rag", target_dir),
}



# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_HELP = """\
Usage: harnessapi <command> [options]

Commands:
  init [project-name]                    New project with greet sample skill
  init --skill <path>                    Add API layer to an existing agentskills.io skill
  init --skills-dir <dir>                Add API layer to all skills in a directory
  init --function <file.py> [--output]   Wrap a Python function as a skill
  examples                               List available example projects
  examples <name> [dir]                  Scaffold an example project locally
  run                                    Start the development server

Options (run):
  --app MODULE:ATTR     App to serve (default: auto-detected)
  --host HOST           Bind host  (default: 127.0.0.1)
  --port PORT           Bind port  (default: 8000)
  --no-reload           Disable auto-reload

Examples:
  harnessapi init my-project
  harnessapi init --skill .agents/skills/summarize
  harnessapi init --skills-dir .agents/skills
  harnessapi init --function utils/compute.py --output skills
  harnessapi examples
  harnessapi examples agentic-rag
  harnessapi examples agentic-rag my-rag-project
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
        # Parse init sub-options
        import argparse
        parser = argparse.ArgumentParser(prog="harnessapi init", add_help=False)
        parser.add_argument("project_name", nargs="?", default=None)
        parser.add_argument("--skill", default=None)
        parser.add_argument("--skills-dir", default=None)
        parser.add_argument("--function", default=None)
        parser.add_argument("--output", default=None)
        opts = parser.parse_args(rest)

        if opts.skill:
            init_skill(opts.skill)
        elif opts.skills_dir:
            init_skills_dir(opts.skills_dir)
        elif opts.function:
            init_function(opts.function, opts.output)
        else:
            init_project(opts.project_name)

    elif command == "examples":
        if not rest:
            print("Available examples:\n")
            for name, desc in _EXAMPLES.items():
                print(f"  {name:<20} {desc}")
            print(f"\nUsage: harnessapi examples <name> [output-dir]")
        else:
            example_name = rest[0]
            if example_name not in _EXAMPLE_SCAFFOLD:
                print(f"Unknown example: '{example_name}'")
                print(f"Available: {', '.join(_EXAMPLES)}")
                sys.exit(1)
            target_name = rest[1] if len(rest) > 1 else example_name
            target_dir = Path.cwd() / target_name
            _EXAMPLE_SCAFFOLD[example_name](target_dir)

    elif command == "run":
        run(rest)

    else:
        print(f"Unknown command: '{command}'")
        print(_HELP)
        sys.exit(1)


if __name__ == "__main__":
    main()
