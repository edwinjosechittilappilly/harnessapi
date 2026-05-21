from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, TYPE_CHECKING

from fastapi import Request

from .registry import TenantSkillRegistry
from .storage import InProcessStorageBackend, StorageBackend

if TYPE_CHECKING:
    pass


@dataclass
class TenantBackend:
    """Configuration object that activates multi-tenancy in HarnessAPI.

    Pass an instance to HarnessAPI(tenant_backend=...) to enable per-tenant
    skill variants and the /tenants/* management API.
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
