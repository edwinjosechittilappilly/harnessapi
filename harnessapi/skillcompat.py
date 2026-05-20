"""Helpers for agentskills.io SKILL.md parsing and compatibility."""
from __future__ import annotations

from pathlib import Path


def parse_skill_md(path: Path) -> tuple[dict, str]:
    """Parse a SKILL.md file into (frontmatter_dict, body_markdown).

    Returns ({}, "") if the file cannot be parsed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}, ""

    # SKILL.md uses YAML frontmatter delimited by --- lines
    if not text.startswith("---"):
        return {}, text.strip()

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text.strip()

    _, raw_yaml, body = parts
    try:
        import tomllib  # noqa: F401 — just confirming stdlib present
        data = _parse_yaml_simple(raw_yaml.strip())
    except Exception:
        data = {}

    return data, body.strip()


def _parse_yaml_simple(raw: str) -> dict:
    """Minimal YAML parser for SKILL.md frontmatter (key: value pairs only).

    We avoid adding PyYAML as a dependency — SKILL.md frontmatter is simple:
    string scalars and optional lists. Falls back to empty dict on anything complex.
    """
    result: dict = {}
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        if ":" in line:
            key, _, rest = line.partition(":")
            key = key.strip()
            rest = rest.strip()
            if rest.startswith("[") and rest.endswith("]"):
                # inline list: [a, b, c]
                items = [v.strip().strip('"').strip("'") for v in rest[1:-1].split(",") if v.strip()]
                result[key] = items
            elif rest == "" or rest == "|" or rest == ">":
                # multi-line value — collect indented lines
                val_lines = []
                i += 1
                while i < len(lines) and (lines[i].startswith("  ") or lines[i].strip() == ""):
                    val_lines.append(lines[i].strip())
                    i += 1
                result[key] = " ".join(val_lines).strip()
                continue
            else:
                result[key] = rest.strip('"').strip("'")
        i += 1
    return result
