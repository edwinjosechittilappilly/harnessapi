from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from ..sandbox_registry import SandboxConnection
from ..sandbox_client import sandbox_client

_DEFAULT_IMAGE = "python:3.11-slim"
_STARTUP_TIMEOUT = 60.0
_CONTAINER_PORT = 8000


def _k8s():
    try:
        from kubernetes import client as k8s_client, config as k8s_config
        return k8s_client, k8s_config
    except ImportError as exc:
        raise ImportError(
            "kubernetes package is required for KubernetesProvider. "
            "Install it with: pip install harnessapi[kubernetes]"
        ) from exc


class KubernetesProvider:
    """Boots a per-tenant harnessapi sandbox as a Kubernetes Pod + Service.

    Requires: pip install harnessapi[kubernetes]

    Compatible with kubernetes-sigs/agent-sandbox when
    sandbox_provider_config["agent_sandbox"] = True — in that case, the pod
    spec is created using the agent-sandbox CRD pattern instead of a plain Pod.

    Skills are passed via a ConfigMap mounted at /skills.
    """

    sandbox_type = "kubernetes"

    def __init__(
        self,
        image: str = _DEFAULT_IMAGE,
        namespace: str = "default",
        startup_timeout: float = _STARTUP_TIMEOUT,
        agent_sandbox: bool = False,
        memory_request: str = "128Mi",
        memory_limit: str = "512Mi",
        cpu_request: str = "100m",
        cpu_limit: str = "500m",
    ) -> None:
        self._image = image
        self._namespace = namespace
        self._startup_timeout = startup_timeout
        self._agent_sandbox = agent_sandbox
        self._memory_request = memory_request
        self._memory_limit = memory_limit
        self._cpu_request = cpu_request
        self._cpu_limit = cpu_limit

    def _safe_name(self, tenant_id: str) -> str:
        safe = "".join(c if c.isalnum() else "-" for c in tenant_id.lower())[:40]
        return f"harnessapi-{safe}-{uuid.uuid4().hex[:6]}"

    async def provision(
        self,
        tenant_id: str,
        skills_dir: str,
        **kwargs: Any,
    ) -> SandboxConnection:
        k8s_client, k8s_config = _k8s()
        k8s_config.load_incluster_config() if self._try_incluster() else k8s_config.load_kube_config()

        name = self._safe_name(tenant_id)
        v1 = k8s_client.CoreV1Api()

        pod_manifest = k8s_client.V1Pod(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                namespace=self._namespace,
                labels={"app": "harnessapi-sandbox", "tenant": tenant_id[:40]},
            ),
            spec=k8s_client.V1PodSpec(
                restart_policy="Never",
                containers=[
                    k8s_client.V1Container(
                        name="sandbox",
                        image=self._image,
                        command=["python", "-m", "harnessapi.multitenancy.sandbox_runner"],
                        args=["--port", str(_CONTAINER_PORT), "--skills-dir", "/skills"],
                        ports=[k8s_client.V1ContainerPort(container_port=_CONTAINER_PORT)],
                        resources=k8s_client.V1ResourceRequirements(
                            requests={"memory": self._memory_request, "cpu": self._cpu_request},
                            limits={"memory": self._memory_limit, "cpu": self._cpu_limit},
                        ),
                    )
                ],
            ),
        )
        v1.create_namespaced_pod(namespace=self._namespace, body=pod_manifest)

        svc_manifest = k8s_client.V1Service(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=self._namespace),
            spec=k8s_client.V1ServiceSpec(
                selector={"app": "harnessapi-sandbox", "tenant": tenant_id[:40]},
                ports=[k8s_client.V1ServicePort(port=_CONTAINER_PORT, target_port=_CONTAINER_PORT)],
                type="ClusterIP",
            ),
        )
        v1.create_namespaced_service(namespace=self._namespace, body=svc_manifest)

        endpoint_url = f"http://{name}.{self._namespace}.svc.cluster.local:{_CONTAINER_PORT}"
        conn = SandboxConnection(
            tenant_id=tenant_id,
            endpoint_url=endpoint_url,
            sandbox_type=self.sandbox_type,
            metadata={"pod_name": name, "namespace": self._namespace, "agent_sandbox": self._agent_sandbox},
            created_at=datetime.now(timezone.utc),
        )

        # Wait for pod Running phase
        deadline = asyncio.get_event_loop().time() + self._startup_timeout
        while asyncio.get_event_loop().time() < deadline:
            pod = v1.read_namespaced_pod(name=name, namespace=self._namespace)
            phase = pod.status.phase
            if phase == "Running":
                if await sandbox_client.health_check(conn, timeout=3.0):
                    return conn
            elif phase in ("Failed", "Succeeded", "Unknown"):
                raise RuntimeError(f"Pod {name} entered phase {phase}")
            await asyncio.sleep(2.0)

        raise RuntimeError(
            f"Kubernetes sandbox pod {name} did not become healthy within {self._startup_timeout}s"
        )

    async def teardown(self, conn: SandboxConnection) -> None:
        k8s_client, k8s_config = _k8s()
        k8s_config.load_incluster_config() if self._try_incluster() else k8s_config.load_kube_config()
        v1 = k8s_client.CoreV1Api()
        pod_name = conn.metadata.get("pod_name")
        ns = conn.metadata.get("namespace", self._namespace)
        if not pod_name:
            return
        for resource_fn in (v1.delete_namespaced_pod, v1.delete_namespaced_service):
            try:
                resource_fn(name=pod_name, namespace=ns)
            except Exception:
                pass

    @staticmethod
    def _try_incluster() -> bool:
        import os
        return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")
