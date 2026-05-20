# harnessapi init commands

## New project from scratch

```bash
harnessapi init my-project
```

Creates:
```
my-project/
├── main.py
├── README.md
├── .gitignore
└── skills/
    └── greet/
        ├── SKILL.md
        ├── handler.py
        ├── models.py
        ├── skill.toml
        ├── defaults/input.json
        └── examples/01.json
```

Then: `cd my-project && harnessapi run`

## Add API layer to an existing agentskills.io skill

```bash
harnessapi init --skill .agents/skills/summarize
```

- Reads `SKILL.md` for name and description
- Adds `handler.py` stub, `models.py` stub, `skill.toml`
- Does NOT modify the existing `SKILL.md`
- Generates a `main.py` one level up if missing

After running: edit `handler.py` and `models.py` to implement the skill logic.

## Add API layer to all skills in a directory

```bash
harnessapi init --skills-dir .agents/skills
```

- Scans for all subfolders with `SKILL.md`
- Adds `handler.py` + `models.py` stubs to each (skips existing files)
- Generates one `main.py` pointing at the directory
- Reports: created / exists (skipped) / no SKILL.md (skipped)

## Wrap a Python function as a skill

```bash
harnessapi init --function utils/compute.py --output skills
```

- Parses the Python file with `ast`
- Finds top-level functions (prompts to pick if multiple)
- Introspects type annotations to generate `models.py` Input fields
- Generates `SKILL.md`, `handler.py`, `models.py`, `skill.toml`
- The handler imports and calls the original function

With a specific output directory:
```bash
harnessapi init --function src/llm.py --output my_app/skills
```

## When to use which command

| Situation | Command |
|---|---|
| Starting fresh | `harnessapi init my-app` |
| You have an agentskills.io skill | `harnessapi init --skill <path>` |
| You have a directory of skills | `harnessapi init --skills-dir <path>` |
| You have a Python function to expose | `harnessapi init --function <file.py>` |
