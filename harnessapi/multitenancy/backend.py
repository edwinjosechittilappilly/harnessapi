from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from fastapi import Request

from .registry import TenantSkillRegistry
from .sandbox_registry import SandboxRegistry
from .storage import InProcessStorageBackend, StorageBackend

if TYPE_CHECKING:
    from .sandbox_providers.base import SandboxProvider


@dataclass
class TenantBackend:
    """Configuration object that activates multi-tenancy in HarnessAPI.

    Pass an instance to HarnessAPI(tenant_backend=...) to enable per-tenant
    skill variants, the /tenants/* management API, and optional per-tenant
    sandbox execution.

    Sandbox usage:
        TenantBackend(
            ...,
            sandbox_registry=SandboxRegistry(),
            sandbox_provider="local_subprocess",          # or "docker" / "kubernetes"
            sandbox_provider_config={},                   # passed to provider __init__
        )
    """

    tenant_extractor: Callable[[Request], Awaitable[str | None]]
    storage: StorageBackend = field(default_factory=InProcessStorageBackend)
    registry: TenantSkillRegistry = field(default_factory=TenantSkillRegistry)
    sandbox_import_blocklist: list[str] = field(
        default_factory=lambda: ["os", "subprocess", "socket", "sys", "importlib", "builtins"]
    )
    auto_promote: bool = False
    max_variants_per_tenant_per_skill: int = 10
    sandbox_run_timeout_secs: float = 10.0
    # Sandbox execution (optional)
    sandbox_registry: SandboxRegistry | None = None
    sandbox_provider: str | SandboxProvider | None = None
    sandbox_provider_config: dict[str, Any] = field(default_factory=dict)
    # Internal — constructed once from sandbox_provider + sandbox_provider_config
    _provider_cache: SandboxProvider | None = field(default=None, init=False, repr=False, compare=False)

    def get_sandbox_provider(self) -> SandboxProvider | None:
        """Return the cached SandboxProvider, constructing it once on first call."""
        if self._provider_cache is None and self.sandbox_provider is not None:
            from .sandbox_providers import get_provider
            self._provider_cache = get_provider(self.sandbox_provider, self.sandbox_provider_config)
        return self._provider_cache
