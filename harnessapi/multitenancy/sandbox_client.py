from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator, TYPE_CHECKING

if TYPE_CHECKING:
    from .sandbox_registry import SandboxConnection

_DEFAULT_TIMEOUT = 30.0


def _httpx_client():
    try:
        import httpx
        return httpx
    except ImportError as exc:
        raise ImportError(
            "httpx is required for sandbox forwarding. "
            "Install it with: pip install harnessapi[sandbox]"
        ) from exc


class SandboxClient:
    """HTTP client for communicating with per-tenant sandbox servers.

    Sandbox-type-agnostic: communicates over HTTP regardless of how the sandbox
    is hosted (subprocess, Docker, Kubernetes, etc.).
    """

    async def health_check(self, conn: SandboxConnection, timeout: float = 5.0) -> bool:
        httpx = _httpx_client()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{conn.endpoint_url}/openapi.json")
                return resp.status_code < 500
        except Exception:
            return False

    async def push_skill(
        self,
        conn: SandboxConnection,
        skill_name: str,
        handler_source: str,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        """Push handler source to the sandbox via its EditRoute endpoint.

        Skips the HTTP round-trip when the source hasn't changed since the last push.
        """
        if conn.last_pushed_source.get(skill_name) == handler_source:
            return
        httpx = _httpx_client()
        headers = {"Content-Type": "application/json"}
        if conn.auth_token:
            headers["Authorization"] = f"Bearer {conn.auth_token}"
        payload = {"source_code": handler_source, "persist": False}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{conn.endpoint_url}/skills/{skill_name}/edit",
                headers=headers,
                content=json.dumps(payload),
            )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"push_skill failed for {skill_name!r} at {conn.endpoint_url}: "
                f"HTTP {resp.status_code} — {resp.text[:200]}"
            )
        conn.last_pushed_source[skill_name] = handler_source

    async def forward(
        self,
        conn: SandboxConnection,
        skill_name: str,
        input_json: dict[str, Any],
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """Forward a skill invocation to the sandbox and return the JSON response."""
        httpx = _httpx_client()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",  # request JSON (not SSE) from sandbox
        }
        if conn.auth_token:
            headers["Authorization"] = f"Bearer {conn.auth_token}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{conn.endpoint_url}/skills/{skill_name}",
                headers=headers,
                content=json.dumps(input_json),
            )
        if resp.status_code == 422:
            raise ValueError(f"Sandbox validation error: {resp.text[:400]}")
        if resp.status_code >= 500:
            raise RuntimeError(f"Sandbox error {resp.status_code}: {resp.text[:400]}")
        # Update last_seen
        conn.last_seen = datetime.now(timezone.utc)
        return resp.json()

    async def forward_sse(
        self,
        conn: SandboxConnection,
        skill_name: str,
        input_json: dict[str, Any],
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> AsyncIterator[dict[str, str]]:
        """Stream SSE events from a sandbox skill back to the caller."""
        httpx = _httpx_client()
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if conn.auth_token:
            headers["Authorization"] = f"Bearer {conn.auth_token}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{conn.endpoint_url}/skills/{skill_name}",
                headers=headers,
                content=json.dumps(input_json),
            ) as resp:
                event_type = "chunk"
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data = line[5:].strip()
                        yield {"data": data, "event": event_type}
                        event_type = "chunk"
                    elif line == "":
                        event_type = "chunk"
        # Update last_seen after stream completes
        conn.last_seen = datetime.now(timezone.utc)


# Module-level singleton — stateless, safe to share
sandbox_client = SandboxClient()
