from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from .decorators import get_registered_skills
from .discovery import SkillsDirectoryProvider
from .exceptions import SkillConflictError
from .mcp import build_mcp_server, register_skill_as_mcp_tool
from .routing import EditRoute, SkillRoute
from .skill import Skill


class HarnessAPI(FastAPI):
    """FastAPI subclass that auto-discovers skills and exposes them as HTTP + MCP."""

    def __init__(
        self,
        *,
        skills_dir: str | Path | None = None,
        mcp_path: str = "/mcp",
        mcp_server_name: str = "HarnessAPI",
        enable_edit_endpoints: bool = False,
        **fastapi_kwargs: Any,
    ) -> None:
        self._mcp = build_mcp_server(mcp_server_name)
        self._skills: dict[str, Skill] = {}
        self._mcp_path = mcp_path
        self._enable_edit = enable_edit_endpoints

        mcp_app = self._mcp.http_app(path="/")
        user_lifespan = fastapi_kwargs.pop("lifespan", None)

        @asynccontextmanager
        async def merged_lifespan(app):
            async with mcp_app.lifespan(mcp_app):
                if user_lifespan is not None:
                    async with user_lifespan(app):
                        yield
                else:
                    yield

        super().__init__(lifespan=merged_lifespan, **fastapi_kwargs)

        # Folder-based discovery
        if skills_dir is not None:
            for skill in SkillsDirectoryProvider(skills_dir).discover():
                self._register_skill(skill)

        # Decorator-based skills
        for skill in get_registered_skills():
            if skill.meta.name not in self._skills:
                self._register_skill(skill)

        # Mount FastMCP ASGI app
        self.mount(mcp_path, mcp_app)

    # ------------------------------------------------------------------
    def _register_skill(self, skill: Skill) -> None:
        name = skill.meta.name
        if name in self._skills:
            raise SkillConflictError(f"Skill '{name}' is already registered")
        self._skills[name] = skill
        self.router.routes.append(SkillRoute(skill))
        if self._enable_edit:
            self.router.routes.append(EditRoute(skill))
        register_skill_as_mcp_tool(self._mcp, skill)

    def add_skill(self, skill: Skill) -> None:
        """Programmatically register a skill after startup."""
        self._register_skill(skill)

    @property
    def skills(self) -> dict[str, Skill]:
        return dict(self._skills)
