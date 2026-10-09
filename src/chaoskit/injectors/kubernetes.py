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
        from kubernetes.client.exceptions import ApiException
        from kubernetes.config.config_exception import ConfigException
        from urllib3.exceptions import MaxRetryError

        # Caught around every API call below so connection/auth failures
        # surface as a clean KubernetesError instead of a raw urllib3 or
        # kubernetes-client traceback.
        self._connection_errors = (MaxRetryError, ApiException)
        try:
            config.load_kube_config()
        except Exception as kubeconfig_exc:
            try:
                config.load_incluster_config()
            except ConfigException as exc:
                # Report both attempts: outside a cluster the in-cluster
                # error alone ("Service host/port is not set") hides the
                # real problem with the user's kubeconfig.
                raise KubernetesError(
                    "could not load a Kubernetes configuration: "
                    f"kubeconfig: {kubeconfig_exc}; in-cluster: {exc}"
                ) from exc
        self._core = client.CoreV1Api()

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except self._connection_errors as exc:
            raise KubernetesError(f"could not reach the Kubernetes API: {exc}") from exc

    def list_pods(self, namespace: str, label_selector: str) -> list[str]:
        pods = self._call(
            self._core.list_namespaced_pod,
            namespace=namespace,
            label_selector=label_selector,
        )
        return [pod.metadata.name for pod in pods.items]

    def delete_pod(self, namespace: str, name: str) -> None:
        self._call(self._core.delete_namespaced_pod, name=name, namespace=namespace)

    def exec_in_pod(self, namespace: str, name: str, command: list[str]) -> None:
        from kubernetes.stream import stream

        self._call(
            stream,
            self._core.connect_get_namespaced_pod_exec,
            name=name,
            namespace=namespace,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
