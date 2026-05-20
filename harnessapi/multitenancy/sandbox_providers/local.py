from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..sandbox_registry import SandboxConnection
from ..sandbox_client import sandbox_client

_DEFAULT_PORT_RANGE = (40000, 50000)
_STARTUP_TIMEOUT = 15.0


def _find_free_port(low: int, high: int) -> int:
    for port in range(low, high):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {low}–{high}")


class LocalSubprocessProvider:
    """Boots a per-tenant harnessapi process on the local machine.

    Uses stdlib only — no Docker or Kubernetes required. Suitable for dev/test
    and single-machine deployments.
    """

    sandbox_type = "local_subprocess"

    def __init__(
        self,
        port_range: tuple[int, int] = _DEFAULT_PORT_RANGE,
        startup_timeout: float = _STARTUP_TIMEOUT,
    ) -> None:
        self._port_range = port_range
        self._startup_timeout = startup_timeout
        self._processes: dict[str, subprocess.Popen] = {}  # tenant_id → process

    async def provision(
        self,
        tenant_id: str,
        skills_dir: str,
        **kwargs: Any,
    ) -> SandboxConnection:
        port = _find_free_port(*self._port_range)

        # Copy base skills into an isolated temp dir so the sandbox has a clean slate
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"harnessapi-sandbox-{tenant_id[:8]}-"))
        src = Path(skills_dir)
        if src.exists():
            shutil.copytree(src, tmp_dir / "skills", dirs_exist_ok=True)
        skills_path = str(tmp_dir / "skills")
        (tmp_dir / "skills").mkdir(exist_ok=True)

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m", "harnessapi.multitenancy.sandbox_runner",
                "--port", str(port),
                "--skills-dir", skills_path,
            ],
            stdin=subprocess.PIPE,  # close stdin to signal teardown
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._processes[tenant_id] = proc

        conn = SandboxConnection(
            tenant_id=tenant_id,
            endpoint_url=f"http://127.0.0.1:{port}",
            sandbox_type=self.sandbox_type,
            pid=proc.pid,
            metadata={"tmp_dir": str(tmp_dir), "port": port},
            created_at=datetime.now(timezone.utc),
        )

        # Wait for the sandbox to be healthy
        deadline = asyncio.get_event_loop().time() + self._startup_timeout
        while asyncio.get_event_loop().time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"Sandbox process exited early (pid={proc.pid})")
            if await sandbox_client.health_check(conn, timeout=2.0):
                return conn
            await asyncio.sleep(0.5)

        proc.terminate()
        raise RuntimeError(
            f"Sandbox for tenant {tenant_id!r} did not become healthy within "
            f"{self._startup_timeout}s on port {port}"
        )

    async def teardown(self, conn: SandboxConnection) -> None:
        import signal as _signal

        proc = self._processes.pop(conn.tenant_id, None)
        pid = conn.pid

        if proc is not None:
            try:
                proc.stdin.close()  # triggers sandbox_runner exit via stdin watcher
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        elif pid is not None:
            try:
                import os
                os.kill(pid, _signal.SIGTERM)
            except ProcessLookupError:
                pass

        # Clean up temp dir
        tmp_dir = conn.metadata.get("tmp_dir")
        if tmp_dir and Path(tmp_dir).exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
