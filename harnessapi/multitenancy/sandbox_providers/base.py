from __future__ import annotations

from typing import Any, Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..sandbox_registry import SandboxConnection


@runtime_checkable
class SandboxProvider(Protocol):
    """Protocol for sandbox execution providers.

    Implement this to add a custom sandbox backend (Modal, E2B, Fly.io, etc.).
    The central server calls provision() once per tenant; thereafter all skill
    invocations are forwarded via HTTP to the returned SandboxConnection.endpoint_url.
    """

    sandbox_type: str

    async def provision(
        self,
        tenant_id: str,
        skills_dir: str,
        **kwargs: Any,
    ) -> SandboxConnection:
        """Boot a sandbox for this tenant and return its connection details."""
        ...

    async def teardown(self, conn: SandboxConnection) -> None:
        """Gracefully shut down and clean up the sandbox."""
        ...
