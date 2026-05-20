"""Tests for SkillsDirectoryProvider and SKILL.md parsing."""
import warnings
from pathlib import Path
import pytest
from harnessapi.discovery import SkillsDirectoryProvider
from harnessapi.skillcompat import parse_skill_md

SKILLS_DIR = Path(__file__).parent / "skills"


def test_discovers_valid_skills():
    skills = list(SkillsDirectoryProvider(SKILLS_DIR).discover())
    names = {s.meta.name for s in skills}
    assert "greet" in names
    assert "echo_stream" in names
    assert "with_defaults" in names


def test_skill_md_only_emits_warning():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        list(SkillsDirectoryProvider(SKILLS_DIR).discover())
    assert any("skill_md_only" in str(warning.message) for warning in w)


def test_skill_md_only_not_loaded_as_api():
    skills = list(SkillsDirectoryProvider(SKILLS_DIR).discover())
    assert not any(s.meta.name == "skill_md_only" for s in skills)


def test_skill_meta_from_toml(skills_dir):
    skills = {s.meta.name: s for s in SkillsDirectoryProvider(skills_dir).discover()}
    greet = skills["greet"]
    assert greet.meta.description == "Greet someone by name"
    assert greet.meta.is_mcp is True
    assert greet.meta.tags == ["demo"]
    assert greet.meta.timeout_secs == 10


def test_skill_md_fields_loaded(skills_dir):
    skills = {s.meta.name: s for s in SkillsDirectoryProvider(skills_dir).discover()}
    greet = skills["greet"]
    assert greet.meta.license == "MIT"
    assert greet.meta.compatibility == "Python 3.11+"
    assert greet.meta.argument_hint == "Who to greet"
    assert greet.meta.instructions is not None
    assert "Say hello" in greet.meta.instructions


def test_toml_overrides_skill_md(skills_dir):
    # skill.toml description wins over SKILL.md description
    skills = {s.meta.name: s for s in SkillsDirectoryProvider(skills_dir).discover()}
    greet = skills["greet"]
    assert greet.meta.description == "Greet someone by name"  # from toml, not SKILL.md


def test_defaults_and_examples_loaded(skills_dir):
    skills = {s.meta.name: s for s in SkillsDirectoryProvider(skills_dir).discover()}
    s = skills["with_defaults"]
    assert s.defaults == {"value": 5}
    assert len(s.examples) == 1
    assert s.examples[0]["input"]["value"] == 3


def test_streaming_handler_detected(skills_dir):
    skills = {s.meta.name: s for s in SkillsDirectoryProvider(skills_dir).discover()}
    assert skills["echo_stream"].is_streaming_handler() is True
    assert skills["greet"].is_streaming_handler() is False


# ── skillcompat ────────────────────────────────────────────────────────────

def test_parse_skill_md_frontmatter():
    skill_md = SKILLS_DIR / "greet" / "SKILL.md"
    data, body = parse_skill_md(skill_md)
    assert data["name"] == "greet"
    assert "greet" in data["description"].lower()
    assert data["license"] == "MIT"
    assert "Say hello" in body


def test_parse_skill_md_missing_file():
    data, body = parse_skill_md(Path("/nonexistent/SKILL.md"))
    assert data == {}
    assert body == ""


def test_parse_skill_md_no_frontmatter(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text("Just plain markdown, no frontmatter.")
    data, body = parse_skill_md(f)
    assert data == {}
    assert "plain markdown" in body
