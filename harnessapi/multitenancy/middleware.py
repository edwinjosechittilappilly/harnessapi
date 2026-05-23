from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class TenantMiddleware(BaseHTTPMiddleware):
    """Extracts tenant_id from the request and stores it in request.state."""

    def __init__(self, app, extractor: Callable[[Request], Awaitable[str | None]]) -> None:
        super().__init__(app)
        self._extractor = extractor

    async def dispatch(self, request: Request, call_next) -> Response:
        import inspect
        result = self._extractor(request)
        tenant_id = await result if inspect.isawaitable(result) else result
        request.state.tenant_id = tenant_id
        return await call_next(request)
