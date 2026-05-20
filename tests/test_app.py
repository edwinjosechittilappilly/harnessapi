"""Tests for HarnessAPI app — HTTP endpoints, JSON and SSE."""
import pytest


def test_registered_skills(app):
    assert "greet" in app.skills
    assert "echo_stream" in app.skills
    assert "with_defaults" in app.skills


def test_skill_conflict(skills_dir):
    from harnessapi import HarnessAPI
    from harnessapi.exceptions import SkillConflictError
    app1 = HarnessAPI(skills_dir=skills_dir)
    with pytest.raises(SkillConflictError):
        from harnessapi.discovery import SkillsDirectoryProvider
        for skill in SkillsDirectoryProvider(skills_dir).discover():
            if skill.meta.name == "greet":
                app1.add_skill(skill)
                break


# ── JSON endpoint ─────────────────────────────────────────────────────────

async def test_greet_json(client):
    r = await client.post(
        "/skills/greet",
        json={"name": "Edwin"},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["message"] == "Hello, Edwin!"


async def test_greet_missing_field(client):
    r = await client.post(
        "/skills/greet",
        json={},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 422


async def test_greet_extra_field_rejected(client):
    r = await client.post(
        "/skills/greet",
        json={"name": "Edwin", "unexpected": "field"},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 422


async def test_with_defaults_json(client):
    r = await client.post(
        "/skills/with_defaults",
        json={"value": 4},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["doubled"] == 8


# ── SSE endpoint ──────────────────────────────────────────────────────────

async def test_greet_sse(client):
    r = await client.post("/skills/greet", json={"name": "World"})
    assert r.status_code == 200
    text = r.text
    assert "event: result" in text
    assert "Hello, World!" in text
    assert "event: done" in text


async def test_echo_stream_sse(client):
    r = await client.post("/skills/echo_stream", json={"text": "hello world"})
    assert r.status_code == 200
    text = r.text
    assert text.count("event: chunk") == 2
    assert "hello" in text
    assert "world" in text
    assert "event: done" in text


async def test_echo_stream_json_collects_chunks(client):
    r = await client.post(
        "/skills/echo_stream",
        json={"text": "one two three"},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 200
    chunks = r.json()["chunks"]
    assert chunks == ["one", "two", "three"]


# ── Edit endpoint ─────────────────────────────────────────────────────────

async def test_edit_endpoint_hot_swap(client):
    new_handler = (
        "from tests.skills.greet.models import Input, Output\n"
        "async def handle(input: Input) -> Output:\n"
        "    return Output(message=f'Hi {input.name}!')\n"
    )
    r = await client.post(
        "/skills/greet/edit",
        json={"source_code": new_handler, "persist": False},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # Verify the new handler is used
    r2 = await client.post(
        "/skills/greet",
        json={"name": "Test"},
        headers={"Accept": "application/json"},
    )
    assert r2.json()["message"] == "Hi Test!"


async def test_edit_endpoint_bad_syntax(client):
    r = await client.post(
        "/skills/greet/edit",
        json={"source_code": "def handle(: broken syntax", "persist": False},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"
    assert "error" in r.json()


async def test_edit_endpoint_no_handle_fn(client):
    r = await client.post(
        "/skills/greet/edit",
        json={"source_code": "x = 1", "persist": False},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"
