"""Tests for the chaos injectors against a fake Kubernetes client."""

import pytest

from chaoskit.experiment import Action
from chaoskit.injectors import (
    InjectionError,
    inject_action,
    inject_cpu_stress,
    inject_network_latency,
    inject_pod_kill,
)

from fakes import FakeKubernetesClient


def _action(type_: str, **params) -> Action:
    return Action(
        type=type_,
        target={"namespace": "default", "label_selector": "app=api"},
        params=params,
    )


@pytest.fixture
def k8s():
    return FakeKubernetesClient(
        {("default", "app=api"): ["api-1", "api-2", "api-3"]}
    )


class TestPodKill:
    def test_deletes_single_pod_by_default(self, k8s):
        description = inject_pod_kill(_action("pod_kill"), k8s)
        assert k8s.deleted == [("default", "api-1")]
        assert "api-1" in description

    def test_deletes_up_to_count_pods(self, k8s):
        inject_pod_kill(_action("pod_kill", count=2), k8s)
        assert k8s.deleted == [("default", "api-1"), ("default", "api-2")]

    def test_count_larger_than_pool_deletes_all(self, k8s):
        inject_pod_kill(_action("pod_kill", count=99), k8s)
        assert len(k8s.deleted) == 3

    def test_deleted_pods_leave_the_listing(self, k8s):
        inject_pod_kill(_action("pod_kill", count=2), k8s)
        assert k8s.list_pods("default", "app=api") == ["api-3"]

    def test_no_matching_pods_raises(self, k8s):
        with pytest.raises(InjectionError, match="no pods found"):
            inject_pod_kill(_action("pod_kill"), FakeKubernetesClient())

    def test_invalid_count_raises(self, k8s):
        with pytest.raises(InjectionError, match="count"):
            inject_pod_kill(_action("pod_kill", count=0), k8s)


class TestCpuStress:
    def test_execs_stress_ng_in_every_matching_pod(self, k8s):
        inject_cpu_stress(_action("cpu_stress"), k8s)
        assert len(k8s.execs) == 3
        namespace, name, command = k8s.execs[0]
        assert (namespace, name) == ("default", "api-1")
        assert command == ["stress-ng", "--cpu", "1", "--timeout", "30s"]

    def test_honors_cores_and_duration_params(self, k8s):
        inject_cpu_stress(_action("cpu_stress", cores=4, duration="90s"), k8s)
        assert k8s.execs[0][2] == ["stress-ng", "--cpu", "4", "--timeout", "90s"]

    def test_duration_accepts_plain_seconds(self, k8s):
        inject_cpu_stress(_action("cpu_stress", duration=45), k8s)
        assert "--timeout" in k8s.execs[0][2]
        assert "45s" in k8s.execs[0][2]

    def test_invalid_duration_raises(self, k8s):
        with pytest.raises(InjectionError, match="duration"):
            inject_cpu_stress(_action("cpu_stress", duration="fast"), k8s)

    def test_no_matching_pods_raises(self):
        with pytest.raises(InjectionError, match="no pods found"):
            inject_cpu_stress(_action("cpu_stress"), FakeKubernetesClient())


class TestNetworkLatency:
    def test_execs_tc_netem_with_cleanup(self, k8s):
        inject_network_latency(_action("network_latency"), k8s)
        assert len(k8s.execs) == 3
        command = " ".join(k8s.execs[0][2])
        assert "tc qdisc add dev eth0 root netem delay 100ms" in command
        assert "sleep 30" in command
        assert "tc qdisc del dev eth0 root netem delay 100ms" in command

    def test_honors_latency_and_duration_params(self, k8s):
        inject_network_latency(
            _action("network_latency", latency_ms=250, duration="60s"), k8s
        )
        command = " ".join(k8s.execs[0][2])
        assert "delay 250ms" in command
        assert "sleep 60" in command

    def test_invalid_latency_raises(self, k8s):
        with pytest.raises(InjectionError, match="latency_ms"):
            inject_network_latency(_action("network_latency", latency_ms=0), k8s)


class TestDispatch:
    def test_dispatches_to_the_right_injector(self, k8s):
        description = inject_action(_action("pod_kill", count=1), k8s)
        assert k8s.deleted == [("default", "api-1")]
        assert "api-1" in description

    def test_unknown_action_type_raises(self, k8s):
        with pytest.raises(InjectionError, match="no injector"):
            inject_action(_action("delete_cluster"), k8s)
