"""Tests for harnessapi CLI — init modes and run command."""
import subprocess
import sys
import pytest

pytestmark = pytest.mark.integration
import textwrap
from pathlib import Path

import pytest


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", *args],
        capture_output=True,
        text=True,
    )


# ── help / unknown command ────────────────────────────────────────────────────

def test_help_exits_zero():
    r = _run_cli("--help")
    assert r.returncode == 0
    assert "init" in r.stdout
    assert "run" in r.stdout


def test_unknown_command_exits_nonzero():
    r = _run_cli("frobnicate")
    assert r.returncode != 0
    assert "Unknown command" in r.stdout


# ── init: default project scaffold ───────────────────────────────────────────

def _init_project_in(tmp_path: Path, name: str) -> Path:
    """Run `harnessapi init <name>` in tmp_path.

    The CLI scaffolds in-place when CWD is empty, or creates <name>/ when not.
    We always pre-create the directory so it scaffolds into <name>/.
    """
    project = tmp_path / name
    project.mkdir()
    # Put a placeholder so the dir is non-empty → CLI creates <name>/ inside CWD
    (tmp_path / ".keep").write_text("")
    subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", name],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    return project


def _scaffold_into_subdir(tmp_path: Path, name: str) -> tuple[Path, subprocess.CompletedProcess]:
    """Run `harnessapi init <name>` in a non-empty tmp_path → creates <name>/ subdir."""
    (tmp_path / "existing.txt").write_text("not empty")
    r = subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", name],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    return tmp_path / name, r


def test_init_project_creates_files(tmp_path):
    project, r = _scaffold_into_subdir(tmp_path, "myproject")
    assert r.returncode == 0
    assert (project / "main.py").exists()
    assert (project / "skills" / "greet" / "handler.py").exists()
    assert (project / "skills" / "greet" / "models.py").exists()
    assert (project / "skills" / "greet" / "SKILL.md").exists()
    assert (project / "skills" / "greet" / "skill.toml").exists()


def test_init_project_skill_md_has_frontmatter(tmp_path):
    project, _ = _scaffold_into_subdir(tmp_path, "proj")
    content = (project / "skills" / "greet" / "SKILL.md").read_text()
    assert "name: greet" in content
    assert "description:" in content


def test_init_project_main_py_is_valid_python(tmp_path):
    project, _ = _scaffold_into_subdir(tmp_path, "proj")
    import ast
    ast.parse((project / "main.py").read_text())


def test_init_project_duplicate_name_exits_nonzero(tmp_path):
    (tmp_path / "existing.txt").write_text("not empty")
    (tmp_path / "existingproject").mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "existingproject"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode != 0
    assert "already exists" in r.stdout


# ── init --skill ──────────────────────────────────────────────────────────────

def test_init_skill_adds_handler_models_toml(tmp_path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Do something useful\n---\n\nInstructions here.\n"
    )
    r = subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--skill", str(skill_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert (skill_dir / "handler.py").exists()
    assert (skill_dir / "models.py").exists()
    assert (skill_dir / "skill.toml").exists()


def test_init_skill_skips_existing_files(tmp_path):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: skill\ndescription: x\n---\n")
    (skill_dir / "handler.py").write_text("# existing\n")
    subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--skill", str(skill_dir)],
        capture_output=True, text=True,
    )
    # handler.py should be unchanged
    assert (skill_dir / "handler.py").read_text() == "# existing\n"


def test_init_skill_no_skill_md_exits_nonzero(tmp_path):
    skill_dir = tmp_path / "empty"
    skill_dir.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--skill", str(skill_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "SKILL.md" in r.stdout


def test_init_skill_missing_dir_exits_nonzero(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--skill", str(tmp_path / "nope")],
        capture_output=True, text=True,
    )
    assert r.returncode != 0


# ── init --skills-dir ─────────────────────────────────────────────────────────

def test_init_skills_dir_scaffolds_all_skills(tmp_path):
    for name in ("alpha", "beta"):
        d = tmp_path / name
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name} skill\n---\n")

    r = subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--skills-dir", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    for name in ("alpha", "beta"):
        assert (tmp_path / name / "handler.py").exists()
        assert (tmp_path / name / "models.py").exists()


def test_init_skills_dir_generates_main_py(tmp_path):
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    d = skill_dir / "mything"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: mything\ndescription: x\n---\n")

    subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--skills-dir", str(skill_dir)],
        capture_output=True, text=True,
    )
    main_py = tmp_path / "main.py"
    assert main_py.exists()
    assert "HarnessAPI" in main_py.read_text()


def test_init_skills_dir_no_skill_md_exits_nonzero(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--skills-dir", str(empty_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0


# ── init --function ───────────────────────────────────────────────────────────

def test_init_function_wraps_single_function(tmp_path):
    fn_file = tmp_path / "utils.py"
    fn_file.write_text(textwrap.dedent("""\
        def compute(x: int, y: int) -> int:
            \"\"\"Add two numbers.\"\"\"
            return x + y
    """))
    out_dir = tmp_path / "skills"
    r = subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--function", str(fn_file),
         "--output", str(out_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    skill_dir = out_dir / "compute"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "handler.py").exists()
    assert (skill_dir / "models.py").exists()
    assert (skill_dir / "skill.toml").exists()


def test_init_function_models_have_input_fields(tmp_path):
    fn_file = tmp_path / "fn.py"
    fn_file.write_text("def greet(name: str, times: int) -> str:\n    return name * times\n")
    out_dir = tmp_path / "skills"
    subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--function", str(fn_file),
         "--output", str(out_dir)],
        capture_output=True, text=True,
    )
    models = (out_dir / "greet" / "models.py").read_text()
    assert "name: str" in models
    assert "times: int" in models


def test_init_function_skill_md_has_frontmatter(tmp_path):
    fn_file = tmp_path / "fn.py"
    fn_file.write_text("def compute(x: int) -> int:\n    \"\"\"Square a number.\"\"\"\n    return x * x\n")
    out_dir = tmp_path / "skills"
    subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--function", str(fn_file),
         "--output", str(out_dir)],
        capture_output=True, text=True,
    )
    skill_md = (out_dir / "compute" / "SKILL.md").read_text()
    assert "name: compute" in skill_md
    assert "description:" in skill_md


def test_init_function_missing_file_exits_nonzero(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--function", str(tmp_path / "nope.py")],
        capture_output=True, text=True,
    )
    assert r.returncode != 0


def test_init_function_no_functions_exits_nonzero(tmp_path):
    fn_file = tmp_path / "empty.py"
    fn_file.write_text("x = 1\ny = 2\n")
    r = subprocess.run(
        [sys.executable, "-m", "harnessapi.cli", "init", "--function", str(fn_file)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "no top-level functions" in r.stdout
