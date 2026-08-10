"""Kubernetes client abstraction for chaos injectors.

Injectors depend only on the small ``KubernetesClient`` protocol, so tests
can substitute a fake and the real client is built lazily — the optional
``kubernetes`` package is only imported when a cluster is actually needed.
"""

from __future__ import annotations

from typing import Protocol


class KubernetesError(RuntimeError):
    """Raised when a Kubernetes operation cannot be performed."""


class KubernetesClient(Protocol):
    """The subset of the Kubernetes API the injectors rely on."""

    def list_pods(self, namespace: str, label_selector: str) -> list[str]:
        """Return the names of pods matching a label selector."""
        ...

    def delete_pod(self, namespace: str, name: str) -> None:
        """Delete a pod and return without waiting for termination."""
        ...

    def exec_in_pod(self, namespace: str, name: str, command: list[str]) -> None:
        """Run a command inside the pod's first container."""
        ...


class CoreV1KubernetesClient:
    """Real client backed by the official ``kubernetes`` package.

    The dependency is imported lazily so that chaos-kit works for validation
    and steady-state checks on machines without the package installed.
    """

    def __init__(self) -> None:
        try:
            from kubernetes import client, config
        except ImportError as exc:
            raise KubernetesError(
                "the 'kubernetes' package is required to inject chaos; "
                "install it with: pip install kubernetes"
            ) from exc
        try:
            config.load_kube_config()
        except Exception:
            config.load_incluster_config()
        self._core = client.CoreV1Api()

    def list_pods(self, namespace: str, label_selector: str) -> list[str]:
        pods = self._core.list_namespaced_pod(
            namespace=namespace, label_selector=label_selector
        )
        return [pod.metadata.name for pod in pods.items]

    def delete_pod(self, namespace: str, name: str) -> None:
        self._core.delete_namespaced_pod(name=name, namespace=namespace)

    def exec_in_pod(self, namespace: str, name: str, command: list[str]) -> None:
        from kubernetes.stream import stream

        stream(
            self._core.connect_get_namespaced_pod_exec,
            name=name,
            namespace=namespace,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
