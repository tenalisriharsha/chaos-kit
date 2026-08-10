"""Chaos injectors: turn experiment actions into Kubernetes operations.

Each injector resolves the action's target (namespace + label selector) to
concrete pods and applies its fault. Injectors return a human-readable
description of what was injected, which the runner records in the result.
"""

from __future__ import annotations

from chaoskit.experiment import Action
from chaoskit.injectors.kubernetes import KubernetesClient


class InjectionError(RuntimeError):
    """Raised when a chaos action cannot be injected."""


def _resolve_pods(action: Action, client: KubernetesClient) -> list[str]:
    namespace = action.target["namespace"]
    selector = action.target["label_selector"]
    pods = client.list_pods(namespace, selector)
    if not pods:
        raise InjectionError(
            f"no pods found matching {selector!r} in namespace {namespace!r}"
        )
    return pods


def _int_param(action: Action, key: str, default: int) -> int:
    value = action.params.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise InjectionError(
            f"{action.type}: params.{key} must be a positive integer, got {value!r}"
        )
    return value


def _duration_seconds(action: Action, default: int) -> int:
    """Parse a duration param given as seconds (int) or a string like '30s'."""
    value = action.params.get("duration", default)
    if isinstance(value, bool):
        value = None
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str) and value.endswith("s") and value[:-1].isdigit():
        seconds = int(value[:-1])
    elif isinstance(value, str) and value.isdigit():
        seconds = int(value)
    else:
        raise InjectionError(
            f"{action.type}: params.duration must be seconds or '<n>s', got {value!r}"
        )
    if seconds < 1:
        raise InjectionError(f"{action.type}: params.duration must be >= 1 second")
    return seconds


def inject_pod_kill(action: Action, client: KubernetesClient) -> str:
    """Delete up to ``params.count`` pods matching the target selector."""
    count = _int_param(action, "count", 1)
    pods = _resolve_pods(action, client)
    victims = pods[:count]
    namespace = action.target["namespace"]
    for name in victims:
        client.delete_pod(namespace, name)
    return f"deleted {len(victims)} pod(s): {', '.join(victims)}"


def inject_cpu_stress(action: Action, client: KubernetesClient) -> str:
    """Run stress-ng inside the target pods to consume CPU.

    Requires the ``stress-ng`` binary in the pod's container image.
    """
    cores = _int_param(action, "cores", 1)
    duration = _duration_seconds(action, default=30)
    pods = _resolve_pods(action, client)
    namespace = action.target["namespace"]
    for name in pods:
        client.exec_in_pod(
            namespace,
            name,
            ["stress-ng", "--cpu", str(cores), "--timeout", f"{duration}s"],
        )
    return (
        f"stressed {cores} core(s) for {duration}s "
        f"in {len(pods)} pod(s): {', '.join(pods)}"
    )


def inject_network_latency(action: Action, client: KubernetesClient) -> str:
    """Add egress latency via tc/netem, self-cleaning after the duration.

    Requires ``tc`` (iproute2) and NET_ADMIN capability in the pod.
    """
    latency_ms = _int_param(action, "latency_ms", 100)
    duration = _duration_seconds(action, default=30)
    pods = _resolve_pods(action, client)
    namespace = action.target["namespace"]
    # Run detached so the qdisc is removed automatically after the duration.
    script = (
        f"tc qdisc add dev eth0 root netem delay {latency_ms}ms; "
        f"sleep {duration}; "
        f"tc qdisc del dev eth0 root netem delay {latency_ms}ms"
    )
    for name in pods:
        client.exec_in_pod(
            namespace, name, ["sh", "-c", f"nohup sh -c '{script}' >/dev/null 2>&1 &"]
        )
    return (
        f"added {latency_ms}ms latency for {duration}s "
        f"in {len(pods)} pod(s): {', '.join(pods)}"
    )


INJECTORS = {
    "pod_kill": inject_pod_kill,
    "cpu_stress": inject_cpu_stress,
    "network_latency": inject_network_latency,
}


def inject_action(action: Action, client: KubernetesClient) -> str:
    """Dispatch an action to its injector and return a description."""
    injector = INJECTORS.get(action.type)
    if injector is None:
        raise InjectionError(f"no injector for action type {action.type!r}")
    return injector(action, client)
