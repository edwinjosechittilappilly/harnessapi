import os
from pathlib import Path
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from harnessapi import HarnessAPI
from harnessapi.multitenancy import TenantBackend, SQLiteStorageBackend, SandboxRegistry
from skills.shared.context import tenant_id_var


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Copies tenant_id from request.state into a ContextVar for skill handlers."""

    async def dispatch(self, request: Request, call_next):
        tid = getattr(request.state, "tenant_id", None) or "default"
        token = tenant_id_var.set(tid)
        try:
            return await call_next(request)
        finally:
            tenant_id_var.reset(token)


async def require_admin_key(request: Request, call_next):
    key = request.headers.get("X-Admin-Key")
    expected = os.environ.get("ADMIN_KEY", "dev-secret")
    if key != expected:
        return JSONResponse({"detail": "Forbidden — provide X-Admin-Key header"}, status_code=403)
    return await call_next(request)


backend = TenantBackend(
    tenant_extractor=lambda req: req.headers.get("X-Tenant-ID") or "default",
    storage=SQLiteStorageBackend(path="./variants.db"),
    sandbox_registry=SandboxRegistry(),
    sandbox_provider="local_subprocess",
    auto_promote=False,
)

app = HarnessAPI(
    skills_dir=Path(__file__).parent / "skills",
    title="Agentic RAG",
    description="Per-tenant document ingestion and semantic search with harnessapi + multi-tenancy",
    tenant_backend=backend,
    enable_admin_mcp=True,
    admin_mcp_auth=require_admin_key,
)

app.add_middleware(TenantContextMiddleware)
