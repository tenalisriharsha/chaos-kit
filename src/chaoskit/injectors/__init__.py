"""Chaos injectors: turn experiment actions into Kubernetes operations.

Each injector resolves the action's target (namespace + label selector) to
concrete pods and applies its fault. Injectors return a human-readable
description of what was injected, which the runner records in the result.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable

from chaoskit.experiment import Action
from chaoskit.injectors.kubernetes import KubernetesClient

# Called with a zero-argument cleanup function for each fault an injector
# starts, so an interrupted run can remove faults still active in the pods.
OnFault = Callable[[Callable[[], None]], None]

_INTERFACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._-]*$")


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


def _interface_param(action: Action) -> str | None:
    """Return params.interface if set, validated as a safe interface name.

    It is interpolated into a shell script, so it is restricted to the
    characters iproute2 interface names actually use.
    """
    value = action.params.get("interface")
    if value is None:
        return None
    if not isinstance(value, str) or not _INTERFACE_RE.match(value):
        raise InjectionError(
            f"{action.type}: params.interface must be a valid network "
            f"interface name, got {value!r}"
        )
    return value


# Resolves the interface to act on: the explicit params.interface when given,
# otherwise the device of the pod's default route. Shared by the script that
# adds the qdisc and the one that removes it, so a Ctrl-C triggered cleanup
# (a separate exec, with no access to the first script's shell variables)
# resolves the same interface without needing it passed back out of the pod.
def _resolve_interface_script(interface: str | None) -> str:
    if interface is not None:
        return f"iface={shlex.quote(interface)}"
    return (
        "iface=$(ip route show default 2>/dev/null | "
        "awk '{for (i=1;i<=NF;i++) if ($i==\"dev\") {print $(i+1); exit}}'); "
        '[ -n "$iface" ] || { '
        "echo 'network_latency: could not detect the default-route "
        "interface (pass params.interface)' >&2; exit 1; }"
    )


def inject_pod_kill(
    action: Action, client: KubernetesClient, on_fault: OnFault | None = None
) -> str:
    """Delete up to ``params.count`` pods matching the target selector."""
    count = _int_param(action, "count", 1)
    pods = _resolve_pods(action, client)
    victims = pods[:count]
    namespace = action.target["namespace"]
    for name in victims:
        client.delete_pod(namespace, name)
    return f"deleted {len(victims)} pod(s): {', '.join(victims)}"


def inject_cpu_stress(
    action: Action, client: KubernetesClient, on_fault: OnFault | None = None
) -> str:
    """Run stress-ng inside the target pods to consume CPU.

    Requires ``sh`` and the ``stress-ng`` binary in the pod's container image.
    """
    cores = _int_param(action, "cores", 1)
    duration = _duration_seconds(action, default=30)
    pods = _resolve_pods(action, client)
    namespace = action.target["namespace"]
    # Run stress-ng detached: exec'd in the foreground it blocked for the
    # whole duration, so pods were stressed one after another and the
    # post-injection check only ran once every stress had ended. The
    # foreground check still fails the exec when stress-ng is missing.
    script = (
        "command -v stress-ng >/dev/null 2>&1 "
        "|| { echo 'stress-ng: not found' >&2; exit 127; }; "
        f"nohup stress-ng --cpu {cores} --timeout {duration}s >/dev/null 2>&1 &"
    )
    for name in pods:
        client.exec_in_pod(namespace, name, ["sh", "-c", script])
    return (
        f"stressed {cores} core(s) for {duration}s "
        f"in {len(pods)} pod(s): {', '.join(pods)}"
    )


def inject_network_latency(
    action: Action, client: KubernetesClient, on_fault: OnFault | None = None
) -> str:
    """Add egress latency via tc/netem, self-cleaning after the duration.

    Requires ``tc`` (iproute2) and NET_ADMIN capability in the pod. Targets
    ``params.interface`` when given, otherwise the device of the pod's
    default route; neither is ``eth0`` on every CNI. Besides the in-pod
    detached cleanup, each pod is registered with ``on_fault`` so an
    interrupted run can remove the qdisc itself instead of waiting out the
    duration.
    """
    latency_ms = _int_param(action, "latency_ms", 100)
    duration = _duration_seconds(action, default=30)
    interface = _interface_param(action)
    pods = _resolve_pods(action, client)
    namespace = action.target["namespace"]
    resolve_iface = _resolve_interface_script(interface)
    # Add the qdisc in the foreground so a missing tc, a missing NET_ADMIN
    # capability or a kernel without netem fails the exec; only the cleanup
    # runs detached, removing the qdisc automatically after the duration.
    # "export iface" lets the detached cleanup inherit the interface this
    # exec resolved, instead of re-resolving it after the duration.
    script = (
        f"{resolve_iface}; export iface; "
        f'tc qdisc add dev "$iface" root netem delay {latency_ms}ms || exit $?; '
        f'nohup sh -c \'sleep {duration}; '
        f'tc qdisc del dev "$iface" root netem delay {latency_ms}ms\' '
        ">/dev/null 2>&1 &"
    )
    # A Ctrl-C triggered cleanup is a fresh exec with none of the shell
    # state above, so it re-resolves the interface the same way.
    remove_script = (
        f'{resolve_iface}; tc qdisc del dev "$iface" root netem delay {latency_ms}ms'
    )
    for name in pods:
        client.exec_in_pod(namespace, name, ["sh", "-c", script])
        if on_fault is not None:
            on_fault(
                lambda ns=namespace, pod=name: client.exec_in_pod(
                    ns, pod, ["sh", "-c", remove_script]
                )
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


def inject_action(
    action: Action, client: KubernetesClient, on_fault: OnFault | None = None
) -> str:
    """Dispatch an action to its injector and return a description."""
    injector = INJECTORS.get(action.type)
    if injector is None:
        raise InjectionError(f"no injector for action type {action.type!r}")
    return injector(action, client, on_fault)
