from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .base import SandboxProvider
from .local import LocalSubprocessProvider

if TYPE_CHECKING:
    pass


def _lazy_docker():
    from .docker import DockerProvider
    return DockerProvider


def _lazy_kubernetes():
    from .kubernetes import KubernetesProvider
    return KubernetesProvider


BUILTIN_PROVIDERS: dict[str, Any] = {
    "local_subprocess": LocalSubprocessProvider,
    # docker and kubernetes are loaded lazily to avoid import errors when their
    # optional dependencies are not installed
    "docker": _lazy_docker,
    "kubernetes": _lazy_kubernetes,
}


def get_provider(
    sandbox_provider: str | SandboxProvider | None,
    sandbox_provider_config: dict[str, Any] | None = None,
) -> SandboxProvider | None:
    """Resolve a sandbox provider from a string name or a pre-constructed instance.

    Returns None when sandbox_provider is None (sandbox feature disabled).
    """
    if sandbox_provider is None:
        return None
    if not isinstance(sandbox_provider, str):
        # Assumed to implement the SandboxProvider protocol already
        return sandbox_provider
    config = sandbox_provider_config or {}
    factory = BUILTIN_PROVIDERS.get(sandbox_provider)
    if factory is None:
        raise ValueError(
            f"Unknown sandbox_provider {sandbox_provider!r}. "
            f"Built-in options: {list(BUILTIN_PROVIDERS)}"
        )
    # Lazy factories return a class; instantiate with config
    cls = factory() if callable(factory) and not isinstance(factory, type) else factory
    return cls(**config)


__all__ = [
    "SandboxProvider",
    "LocalSubprocessProvider",
    "get_provider",
    "BUILTIN_PROVIDERS",
]
