from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport
from harnessapi import HarnessAPI

SKILLS_DIR = Path(__file__).parent / "skills"


@pytest.fixture(scope="session")
def skills_dir() -> Path:
    return SKILLS_DIR


@pytest.fixture(scope="session")
def app() -> HarnessAPI:
    return HarnessAPI(
        skills_dir=SKILLS_DIR,
        mcp_server_name="test-harness",
        enable_edit_endpoints=True,
    )


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
