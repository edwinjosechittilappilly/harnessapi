from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TYPE_CHECKING

from fastapi import FastAPI

from .decorators import get_registered_skills
from .discovery import SkillsDirectoryProvider
from .exceptions import SkillConflictError
from .mcp import build_mcp_server, register_skill_as_mcp_tool
from .routing import EditRoute, SkillRoute
from .skill import Skill

if TYPE_CHECKING:
    from .multitenancy.backend import TenantBackend


class HarnessAPI(FastAPI):
    """FastAPI subclass that auto-discovers skills and exposes them as HTTP + MCP."""

    def __init__(
        self,
        *,
        skills_dir: str | Path | None = None,
        mcp_path: str = "/mcp",
        mcp_server_name: str = "HarnessAPI",
        enable_edit_endpoints: bool = False,
        tenant_backend: TenantBackend | None = None,
        **fastapi_kwargs: Any,
    ) -> None:
        self._mcp = build_mcp_server(mcp_server_name)
        self._skills: dict[str, Skill] = {}
        self._mcp_path = mcp_path
        self._enable_edit = enable_edit_endpoints
        self._tenant_backend = tenant_backend

        mcp_app = self._mcp.http_app(path="/")
        user_lifespan = fastapi_kwargs.pop("lifespan", None)

        @asynccontextmanager
        async def merged_lifespan(app):
            async with mcp_app.lifespan(mcp_app):
                if tenant_backend is not None:
                    await _load_tenant_variants(tenant_backend, self._skills)
                    await _restore_sandbox_connections(tenant_backend)
                if user_lifespan is not None:
                    async with user_lifespan(app):
                        yield
                else:
                    yield

        super().__init__(lifespan=merged_lifespan, **fastapi_kwargs)

        # Inject tenant middleware before route registration
        if tenant_backend is not None:
            from .multitenancy.middleware import TenantMiddleware
            self.add_middleware(TenantMiddleware, extractor=tenant_backend.tenant_extractor)

        # Folder-based discovery
        if skills_dir is not None:
            for skill in SkillsDirectoryProvider(skills_dir).discover():
                self._register_skill(skill)

        # Decorator-based skills
        for skill in get_registered_skills():
            if skill.meta.name not in self._skills:
                self._register_skill(skill)

        # Register tenant management router
        if tenant_backend is not None:
            from .multitenancy.router import build_tenant_router
            self.include_router(build_tenant_router(tenant_backend, self._skills))

        # Mount FastMCP ASGI app
        self.mount(mcp_path, mcp_app)

    # ------------------------------------------------------------------
    def _register_skill(self, skill: Skill) -> None:
        name = skill.meta.name
        if name in self._skills:
            raise SkillConflictError(f"Skill '{name}' is already registered")
        self._skills[name] = skill
        tenant_registry = self._tenant_backend.registry if self._tenant_backend else None
        sandbox_registry = self._tenant_backend.sandbox_registry if self._tenant_backend else None
        self.router.routes.append(
            SkillRoute(skill, tenant_registry=tenant_registry, sandbox_registry=sandbox_registry)
        )
        if self._enable_edit:
            self.router.routes.append(EditRoute(skill))
        register_skill_as_mcp_tool(self._mcp, skill)

    def add_skill(self, skill: Skill) -> None:
        """Programmatically register a skill after startup."""
        self._register_skill(skill)

    @property
    def skills(self) -> dict[str, Skill]:
        return dict(self._skills)


async def _load_tenant_variants(tenant_backend: TenantBackend, base_skills: dict[str, Skill]) -> None:
    """Restore promoted variants from storage into the in-memory registry at startup."""
    from datetime import datetime, timezone
    from .multitenancy.sandbox import compile_variant_handler
    from .multitenancy.models import SkillVariant
    from .multitenancy.storage import _PartialVariant

    partials = await tenant_backend.storage.load_promoted_variants()
    for p in partials:
        base = base_skills.get(p.base_skill_name)
        if base is None:
            continue  # base skill no longer exists; skip stale variant
        try:
            handler = compile_variant_handler(p.handler_source, p.base_skill_name, p.variant_id)
        except ValueError:
            continue  # corrupted source; skip
        variant = SkillVariant(
            variant_id=p.variant_id,
            tenant_id=p.tenant_id,
            base_skill_name=p.base_skill_name,
            handler_source=p.handler_source,
            handler=handler,
            status="promoted",
            created_at=datetime.fromisoformat(p.created_at_str),
            input_model=base.input_model,
            output_model=base.output_model,
            meta_overrides=p.meta_overrides,
        )
        tenant_backend.registry.set_promoted(variant)


async def _restore_sandbox_connections(tenant_backend: TenantBackend) -> None:
    """Restore sandbox connections from storage into the in-memory SandboxRegistry."""
    if tenant_backend.sandbox_registry is None:
        return
    if not hasattr(tenant_backend.storage, "load_sandboxes"):
        return
    from datetime import datetime, timezone
    from .multitenancy.sandbox_registry import SandboxConnection

    rows = await tenant_backend.storage.load_sandboxes()
    for row in rows:
        conn = SandboxConnection(
            tenant_id=row["tenant_id"],
            endpoint_url=row["endpoint_url"],
            sandbox_type=row["sandbox_type"],
            pid=row.get("pid"),
            auth_token=row.get("auth_token"),
            metadata=row.get("metadata", {}),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen=datetime.fromisoformat(row["last_seen"]) if row.get("last_seen") else None,
        )
        tenant_backend.sandbox_registry.register(conn)
