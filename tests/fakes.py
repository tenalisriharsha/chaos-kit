"""A fake KubernetesClient for tests: pods in memory, calls recorded."""

from __future__ import annotations


class FakeKubernetesClient:
    """Implements the KubernetesClient protocol without a cluster.

    ``pods`` maps (namespace, label_selector) to pod names. Deleting a pod
    removes it from the listing so later calls observe the change.
    """

    def __init__(self, pods: dict[tuple[str, str], list[str]] | None = None):
        self._pods = {key: list(names) for key, names in (pods or {}).items()}
        self.deleted: list[tuple[str, str]] = []
        self.execs: list[tuple[str, str, list[str]]] = []

    def list_pods(self, namespace: str, label_selector: str) -> list[str]:
        return list(self._pods.get((namespace, label_selector), []))

    def delete_pod(self, namespace: str, name: str) -> None:
        self.deleted.append((namespace, name))
        for key, names in self._pods.items():
            if key[0] == namespace and name in names:
                names.remove(name)

    def exec_in_pod(self, namespace: str, name: str, command: list[str]) -> None:
        self.execs.append((namespace, name, command))
