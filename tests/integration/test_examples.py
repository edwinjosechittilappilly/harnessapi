"""Tests for `harnessapi examples` — scaffold bundled example projects."""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


# ── examples list ─────────────────────────────────────────────────────────────

def test_examples_list_exits_zero():
    r = _run_cli("examples")
    assert r.returncode == 0


def test_examples_list_shows_agentic_rag():
    r = _run_cli("examples")
    assert "agentic-rag" in r.stdout


# ── agentic-rag scaffold ──────────────────────────────────────────────────────

def test_examples_agentic_rag_scaffolds_into_dir(tmp_path):
    r = _run_cli("examples", "agentic-rag", str(tmp_path / "my-rag"), cwd=tmp_path)
    assert r.returncode == 0
    assert (tmp_path / "my-rag").is_dir()


def test_examples_agentic_rag_creates_main_py(tmp_path):
    _run_cli("examples", "agentic-rag", str(tmp_path / "rag"), cwd=tmp_path)
    assert (tmp_path / "rag" / "main.py").exists()


def test_examples_agentic_rag_main_py_is_valid_python(tmp_path):
    _run_cli("examples", "agentic-rag", str(tmp_path / "rag"), cwd=tmp_path)
    src = (tmp_path / "rag" / "main.py").read_text()
    ast.parse(src)


def test_examples_agentic_rag_creates_skills_dir(tmp_path):
    _run_cli("examples", "agentic-rag", str(tmp_path / "rag"), cwd=tmp_path)
    assert (tmp_path / "rag" / "skills").is_dir()


def test_examples_agentic_rag_has_expected_skills(tmp_path):
    _run_cli("examples", "agentic-rag", str(tmp_path / "rag"), cwd=tmp_path)
    skills = {p.name for p in (tmp_path / "rag" / "skills").iterdir() if p.is_dir()}
    assert {"ingest", "search", "list_docs", "shared"}.issubset(skills)


def test_examples_agentic_rag_handlers_are_valid_python(tmp_path):
    _run_cli("examples", "agentic-rag", str(tmp_path / "rag"), cwd=tmp_path)
    for handler in (tmp_path / "rag" / "skills").rglob("handler.py"):
        ast.parse(handler.read_text())


def test_examples_agentic_rag_has_env_example(tmp_path):
    _run_cli("examples", "agentic-rag", str(tmp_path / "rag"), cwd=tmp_path)
    assert (tmp_path / "rag" / ".env.example").exists()


def test_examples_agentic_rag_duplicate_target_exits_nonzero(tmp_path):
    target = tmp_path / "rag"
    target.mkdir()
    r = _run_cli("examples", "agentic-rag", str(target), cwd=tmp_path)
    assert r.returncode != 0
    assert "already exists" in r.stdout


def test_examples_unknown_name_exits_nonzero(tmp_path):
    r = _run_cli("examples", "nonexistent-example", cwd=tmp_path)
    assert r.returncode != 0
