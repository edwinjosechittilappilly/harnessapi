---
title: harnessapi init
description: Reference for the harnessapi init CLI command — scaffold new projects, convert agentskills.io skills, and wrap Python functions.
---

Scaffolds a new harnessapi project or adds the harnessapi layer to existing skill folders.

## Usage

```
harnessapi init [project-name]
harnessapi init --skill <path>
harnessapi init --skills-dir <dir>
harnessapi init --function <file.py> [--output <dir>]
```

---

## Default — new project

```bash
harnessapi init my-project
```

Creates a new project with a sample `greet` skill:

```
my-project/
├── main.py
├── README.md
├── .gitignore
└── skills/
    └── greet/
        ├── handler.py
        ├── models.py
        ├── SKILL.md
        ├── skill.toml
        ├── defaults/
        │   └── input.json
        └── examples/
            └── 01.json
```

If run in an empty directory, scaffolds in-place instead of creating a subdirectory.

---

## `--skill` — add API layer to an existing skill

```bash
harnessapi init --skill .agents/skills/summarize
```

Reads the existing `SKILL.md`, then adds:
- `handler.py` — stub with `TODO` comments
- `models.py` — stub Input and Output classes
- `skill.toml` — populated from `SKILL.md` frontmatter

Skips any file that already exists. Never modifies `SKILL.md`.

---

## `--skills-dir` — convert a whole directory

```bash
harnessapi init --skills-dir .agents/skills
```

Scans for all subfolders containing `SKILL.md`, adds stubs to each, and generates a top-level `main.py` pointing at the directory.

---

## `--function` — wrap a Python function

```bash
harnessapi init --function utils/compute.py --output skills
```

Uses Python `ast` to introspect the function's signature (no import needed), then generates:
- `skills/<func-name>/SKILL.md` — from docstring
- `skills/<func-name>/models.py` — Input fields from parameters
- `skills/<func-name>/handler.py` — calls the original function
- `skills/<func-name>/skill.toml`

If multiple functions exist in the file, you are prompted to choose one.

**Options:**

| Flag | Description |
|------|-------------|
| `--output <dir>` | Output directory for the skill folder (default: `./skills`) |
