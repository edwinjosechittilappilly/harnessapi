from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from ..sandbox_registry import SandboxConnection
from ..sandbox_client import sandbox_client

_DEFAULT_IMAGE = "python:3.11-slim"
_STARTUP_TIMEOUT = 30.0
_CONTAINER_PORT = 8000


def _docker():
    try:
        import docker
        return docker
    except ImportError as exc:
        raise ImportError(
            "docker package is required for DockerProvider. "
            "Install it with: pip install harnessapi[docker]"
        ) from exc


class DockerProvider:
    """Boots a per-tenant harnessapi sandbox in a Docker container.

    Requires: pip install harnessapi[docker]

    Each tenant gets an isolated container. The container image must have
    harnessapi installed and expose port 8000 via the sandbox_runner module.

    Recommended Dockerfile snippet:
        FROM python:3.11-slim
        RUN pip install harnessapi[sandbox]
        ENTRYPOINT ["python", "-m", "harnessapi.multitenancy.sandbox_runner"]
    """

    sandbox_type = "docker"

    def __init__(
        self,
        image: str = _DEFAULT_IMAGE,
        memory_limit: str = "512m",
        cpu_period: int = 100000,
        cpu_quota: int = 50000,
        startup_timeout: float = _STARTUP_TIMEOUT,
        extra_run_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self._image = image
        self._memory_limit = memory_limit
        self._cpu_period = cpu_period
        self._cpu_quota = cpu_quota
        self._startup_timeout = startup_timeout
        self._extra_run_kwargs = extra_run_kwargs or {}

    async def provision(
        self,
        tenant_id: str,
        skills_dir: str,
        **kwargs: Any,
    ) -> SandboxConnection:
        docker = _docker()
        client = docker.from_env()

        container = client.containers.run(
            self._image,
            command=[
                "--port", str(_CONTAINER_PORT),
                "--skills-dir", "/skills",
            ],
            detach=True,
            remove=True,
            ports={f"{_CONTAINER_PORT}/tcp": None},  # random host port
            volumes={skills_dir: {"bind": "/skills", "mode": "ro"}},
            mem_limit=self._memory_limit,
            cpu_period=self._cpu_period,
            cpu_quota=self._cpu_quota,
            **self._extra_run_kwargs,
        )

        # Reload to get the assigned host port
        container.reload()
        host_port = container.ports[f"{_CONTAINER_PORT}/tcp"][0]["HostPort"]
        endpoint_url = f"http://127.0.0.1:{host_port}"

        conn = SandboxConnection(
            tenant_id=tenant_id,
            endpoint_url=endpoint_url,
            sandbox_type=self.sandbox_type,
            metadata={"container_id": container.id, "host_port": host_port},
            created_at=datetime.now(timezone.utc),
        )

        # Wait for healthy
        deadline = asyncio.get_event_loop().time() + self._startup_timeout
        while asyncio.get_event_loop().time() < deadline:
            container.reload()
            if container.status not in ("created", "running"):
                raise RuntimeError(f"Container {container.short_id} entered status: {container.status}")
            if await sandbox_client.health_check(conn, timeout=2.0):
                return conn
            await asyncio.sleep(1.0)

        container.stop(timeout=5)
        raise RuntimeError(
            f"Docker sandbox for tenant {tenant_id!r} did not become healthy within "
            f"{self._startup_timeout}s"
        )

    async def teardown(self, conn: SandboxConnection) -> None:
        docker = _docker()
        container_id = conn.metadata.get("container_id")
        if not container_id:
            return
        try:
            client = docker.from_env()
            container = client.containers.get(container_id)
            container.stop(timeout=5)
        except Exception:
            pass
