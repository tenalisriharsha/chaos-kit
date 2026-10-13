"""Tests for the chaos injectors against a fake Kubernetes client."""

import os
import subprocess
import time

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


def _fake_bin(tmp_path, name, body):
    """Write an executable shell script ``name`` into tmp_path/bin."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return bin_dir


def _run_in_pod_shell(command, bin_dir):
    """Run an exec'd command locally, as the pod's shell would."""
    env = dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin")
    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


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
        assert command[:2] == ["sh", "-c"]
        assert "stress-ng --cpu 1 --timeout 30s" in command[2]

    def test_honors_cores_and_duration_params(self, k8s):
        inject_cpu_stress(_action("cpu_stress", cores=4, duration="90s"), k8s)
        assert "stress-ng --cpu 4 --timeout 90s" in k8s.execs[0][2][2]

    def test_duration_accepts_plain_seconds(self, k8s):
        inject_cpu_stress(_action("cpu_stress", duration=45), k8s)
        assert "--timeout 45s" in k8s.execs[0][2][2]

    def test_exec_returns_while_stress_keeps_running(self, k8s, tmp_path):
        # Seen on a real cluster: the exec blocked for the full duration,
        # so two pods were stressed one after the other and the post-check
        # ran after all stress had ended.
        log = tmp_path / "stress.log"
        bin_dir = _fake_bin(tmp_path, "stress-ng", f'echo "$*" >> {log}; sleep 3')
        inject_cpu_stress(_action("cpu_stress", cores=2, duration=3), k8s)
        started = time.monotonic()
        proc = _run_in_pod_shell(k8s.execs[0][2], bin_dir)
        assert proc.returncode == 0
        assert time.monotonic() - started < 2
        assert _wait_for(lambda: log.exists() and log.read_text())
        assert log.read_text() == "--cpu 2 --timeout 3s\n"

    def test_missing_stress_ng_fails_the_exec(self, k8s, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        if any(os.access(f"{d}/stress-ng", os.X_OK) for d in ("/usr/bin", "/bin")):
            pytest.skip("stress-ng is installed on this machine")
        inject_cpu_stress(_action("cpu_stress"), k8s)
        proc = _run_in_pod_shell(k8s.execs[0][2], bin_dir)
        assert proc.returncode == 127
        assert "stress-ng: not found" in proc.stderr

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

    def test_tc_failure_fails_the_exec(self, k8s, tmp_path):
        # Seen on a real cluster: a kernel without netem made tc fail, but
        # the whole script ran detached with output discarded, so the exec
        # succeeded and the latency was reported as injected.
        bin_dir = _fake_bin(
            tmp_path, "tc", "echo 'Error: Specified qdisc kind is unknown.' >&2; exit 2"
        )
        inject_network_latency(_action("network_latency"), k8s)
        proc = _run_in_pod_shell(k8s.execs[0][2], bin_dir)
        assert proc.returncode == 2
        assert "qdisc kind is unknown" in proc.stderr

    def test_adds_qdisc_now_and_removes_it_after_duration(self, k8s, tmp_path):
        log = tmp_path / "tc.log"
        bin_dir = _fake_bin(tmp_path, "tc", f'echo "$*" >> {log}')
        inject_network_latency(_action("network_latency", duration=1), k8s)
        proc = _run_in_pod_shell(k8s.execs[0][2], bin_dir)
        assert proc.returncode == 0
        assert log.read_text() == "qdisc add dev eth0 root netem delay 100ms\n"
        assert _wait_for(lambda: "qdisc del" in log.read_text())


class TestDispatch:
    def test_dispatches_to_the_right_injector(self, k8s):
        description = inject_action(_action("pod_kill", count=1), k8s)
        assert k8s.deleted == [("default", "api-1")]
        assert "api-1" in description

    def test_unknown_action_type_raises(self, k8s):
        with pytest.raises(InjectionError, match="no injector"):
            inject_action(_action("delete_cluster"), k8s)
