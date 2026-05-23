from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SandboxConnection:
    tenant_id: str
    endpoint_url: str
    sandbox_type: str           # "local_subprocess" | "docker" | "kubernetes" | custom
    pid: int | None = None      # subprocess PID (local_subprocess only)
    auth_token: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    last_seen: datetime | None = None
    last_pushed_source: dict[str, str] = field(default_factory=dict)  # skill_name → source (in-memory only)


class SandboxRegistry:
    """In-memory index of per-tenant sandbox connections."""

    def __init__(self) -> None:
        self._connections: dict[str, SandboxConnection] = {}  # tenant_id → connection

    def register(self, conn: SandboxConnection) -> None:
        self._connections[conn.tenant_id] = conn

    def get(self, tenant_id: str) -> SandboxConnection | None:
        return self._connections.get(tenant_id)

    def deregister(self, tenant_id: str) -> SandboxConnection | None:
        return self._connections.pop(tenant_id, None)

    def list_all(self) -> list[SandboxConnection]:
        return list(self._connections.values())
