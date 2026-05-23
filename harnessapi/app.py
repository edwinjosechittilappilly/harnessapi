from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from .decorators import get_registered_skills
from .discovery import SkillsDirectoryProvider
from .exceptions import SkillConflictError
from .mcp import build_mcp_server, register_skill_as_mcp_tool
from .routing import EditRoute, SkillRoute
from .skill import Skill

if TYPE_CHECKING:
    from .multitenancy.backend import TenantBackend


class _AdminAuthWrapper:
    """Thin ASGI wrapper that calls admin_mcp_auth before dispatching HTTP requests.

    auth_fn signature: async (request, call_next) -> Response
    If auth_fn returns a response directly (e.g. 403) the inner app is never called.
    call_next forwards the request through the inner app using the real send callable
    and returns a sentinel Response (the inner app writes directly to send).
    """

    def __init__(self, app, auth_fn: Callable[[Request, Callable], Awaitable[Response]]) -> None:
        self._app = app
        self._auth_fn = auth_fn

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        request = Request(scope, receive)
        _forwarded = False

        async def call_next(req: Request) -> Response:
            nonlocal _forwarded
            _forwarded = True
            await self._app(scope, receive, send)
            # Return a sentinel — the inner app already wrote to send directly
            return Response(b"")

        response = await self._auth_fn(request, call_next)
        if not _forwarded:
            # Auth rejected — send the rejection response
            await response(scope, receive, send)


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
        enable_admin_mcp: bool = False,
        admin_mcp_path: str = "/admin-mcp",
        admin_mcp_auth: Callable[[Request, Callable], Awaitable[Response]] | None = None,
        **fastapi_kwargs: Any,
    ) -> None:
        self._mcp = build_mcp_server(mcp_server_name)
        self._skills: dict[str, Skill] = {}
        self._mcp_path = mcp_path
        self._enable_edit = enable_edit_endpoints
        self._tenant_backend = tenant_backend

        mcp_app = self._mcp.http_app(path="/")
        user_lifespan = fastapi_kwargs.pop("lifespan", None)

        # Build admin MCP app eagerly (needs self._skills populated later, so deferred)
        self._admin_mcp_app = None
        self._enable_admin_mcp = enable_admin_mcp and tenant_backend is not None
        self._admin_mcp_path = admin_mcp_path

        @asynccontextmanager
        async def _inner_lifespan(app):
            if tenant_backend is not None:
                await _load_tenant_variants(tenant_backend, self._skills)
                await _restore_sandbox_connections(tenant_backend)
            if user_lifespan is not None:
                async with user_lifespan(app):
                    yield
            else:
                yield

        @asynccontextmanager
        async def merged_lifespan(app):
            async with mcp_app.lifespan(mcp_app):
                if self._admin_mcp_app is not None:
                    async with self._admin_mcp_app.lifespan(self._admin_mcp_app):
                        async with _inner_lifespan(app):
                            yield
                else:
                    async with _inner_lifespan(app):
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

        # Mount admin MCP server (opt-in, only when tenant_backend is set)
        if self._enable_admin_mcp:
            from .multitenancy.admin_mcp import build_admin_mcp_server
            admin_mcp = build_admin_mcp_server(tenant_backend, self._skills)
            self._admin_mcp_app = admin_mcp.http_app(path="/")
            asgi_app = self._admin_mcp_app
            if admin_mcp_auth is not None:
                asgi_app = _AdminAuthWrapper(asgi_app, admin_mcp_auth)
            self.mount(admin_mcp_path, asgi_app)

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
    """Restore promoted and preview variants from storage into the in-memory registry at startup."""
    from datetime import datetime, timezone
    from .multitenancy.sandbox import compile_variant_handler
    from .multitenancy.models import SkillVariant

    def _restore_partials(partials, status: str, register_fn):
        for p in partials:
            base = base_skills.get(p.base_skill_name)
            if base is None:
                continue
            try:
                handler = compile_variant_handler(p.handler_source, p.base_skill_name, p.variant_id)
            except ValueError:
                continue
            variant = SkillVariant(
                variant_id=p.variant_id,
                tenant_id=p.tenant_id,
                base_skill_name=p.base_skill_name,
                handler_source=p.handler_source,
                handler=handler,
                status=status,
                created_at=datetime.fromisoformat(p.created_at_str),
                input_model=base.input_model,
                output_model=base.output_model,
                meta_overrides=p.meta_overrides,
            )
            register_fn(variant)

    promoted = await tenant_backend.storage.load_promoted_variants()
    _restore_partials(promoted, "promoted", tenant_backend.registry.set_promoted)

    if hasattr(tenant_backend.storage, "load_preview_variants"):
        preview = await tenant_backend.storage.load_preview_variants()
        _restore_partials(preview, "preview", tenant_backend.registry.set_preview)


async def _restore_sandbox_connections(tenant_backend: TenantBackend) -> None:
    """Restore sandbox connections from storage, dropping any that are unreachable.

    Sandboxes (especially local_subprocess) do not survive server restarts.
    Registering a stale connection would cause 502 errors on every tenant request
    until the operator manually re-provisions. We health-check each connection and
    only register it if the sandbox is still reachable.
    """
    if tenant_backend.sandbox_registry is None:
        return
    if not hasattr(tenant_backend.storage, "load_sandboxes"):
        return
    from datetime import datetime
    from .multitenancy.sandbox_registry import SandboxConnection
    from .multitenancy.sandbox_client import sandbox_client

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
        if await sandbox_client.health_check(conn):
            tenant_backend.sandbox_registry.register(conn)
        elif hasattr(tenant_backend.storage, "delete_sandbox"):
            # Remove the stale record so it doesn't re-appear on the next restart
            await tenant_backend.storage.delete_sandbox(conn.tenant_id)
