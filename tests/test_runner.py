"""Tests for the experiment runner's orchestration flow."""

import pytest

from chaoskit.experiment import parse_experiment
from chaoskit.runner import run_experiment

from fakes import FakeKubernetesClient


class FakeMetricsClient:
    """Serves queued query results, one per call."""

    def __init__(self, values: list[float]):
        self._values = list(values)
        self.queries: list[str] = []

    def query(self, promql: str) -> float:
        self.queries.append(promql)
        if not self._values:
            raise AssertionError("unexpected extra query")
        return self._values.pop(0)


def _experiment() -> object:
    return parse_experiment(
        {
            "name": "demo",
            "steady_state": [
                {
                    "name": "low-errors",
                    "query": "error_rate",
                    "operator": "lt",
                    "threshold": 0.5,
                }
            ],
            "actions": [
                {
                    "type": "pod_kill",
                    "target": {"namespace": "default", "label_selector": "app=api"},
                    "params": {"count": 1},
                }
            ],
        }
    )


@pytest.fixture
def k8s():
    return FakeKubernetesClient({("default", "app=api"): ["api-1", "api-2"]})


def test_happy_path_injects_and_rechecks(k8s):
    # pre-check: 0.1 (pass), post-check: 0.2 (pass)
    metrics = FakeMetricsClient([0.1, 0.2])
    slept: list[float] = []
    result = run_experiment(_experiment(), metrics, k8s, settle_seconds=42, sleep=slept.append)

    assert result.passed
    assert not result.aborted
    assert k8s.deleted == [("default", "api-1")]
    assert slept == [42.0]
    assert [r.passed for r in result.pre_check] == [True]
    assert [r.passed for r in result.post_check] == [True]
    assert result.injections[0].action_type == "pod_kill"
    assert result.injections[0].target == "default/app=api"


def test_aborts_without_injecting_when_pre_check_fails(k8s):
    metrics = FakeMetricsClient([0.9])
    result = run_experiment(_experiment(), metrics, k8s, sleep=lambda s: None)

    assert result.aborted
    assert not result.passed
    assert result.post_check is None
    assert k8s.deleted == []
    assert result.injections == []


def test_fails_when_system_does_not_recover(k8s):
    # pre-check passes, post-check violates the hypothesis
    metrics = FakeMetricsClient([0.1, 0.9])
    result = run_experiment(_experiment(), metrics, k8s, sleep=lambda s: None)

    assert not result.aborted
    assert not result.passed
    assert k8s.deleted == [("default", "api-1")]
    assert [r.passed for r in result.post_check] == [False]


def test_runs_actions_in_order(k8s):
    exp = parse_experiment(
        {
            "name": "multi",
            "steady_state": [
                {"name": "p", "query": "q", "operator": "lt", "threshold": 1}
            ],
            "actions": [
                {
                    "type": "pod_kill",
                    "target": {"namespace": "default", "label_selector": "app=api"},
                },
                {
                    "type": "cpu_stress",
                    "target": {"namespace": "default", "label_selector": "app=api"},
                    "params": {"duration": 5},
                },
            ],
        }
    )
    metrics = FakeMetricsClient([0.1, 0.1])
    result = run_experiment(exp, metrics, k8s, sleep=lambda s: None)

    assert [r.action_type for r in result.injections] == ["pod_kill", "cpu_stress"]
    # cpu_stress ran after the kill and sees only the remaining pod
    assert [name for _, name, _ in k8s.execs] == ["api-2"]


def test_injection_error_is_recorded_not_raised():
    metrics = FakeMetricsClient([0.1])
    result = run_experiment(
        _experiment(), metrics, FakeKubernetesClient(), sleep=lambda s: None
    )

    assert result.partial_failure
    assert "no pods found" in result.injection_error
    assert not result.passed
    assert result.injections == []
    assert result.post_check is None


def test_later_action_failure_reports_earlier_injections(k8s):
    exp = parse_experiment(
        {
            "name": "multi",
            "steady_state": [
                {"name": "p", "query": "q", "operator": "lt", "threshold": 1}
            ],
            "actions": [
                {
                    "type": "pod_kill",
                    "target": {"namespace": "default", "label_selector": "app=api"},
                    "params": {"count": 1},
                },
                {
                    "type": "cpu_stress",
                    "target": {"namespace": "default", "label_selector": "app=missing"},
                },
                {
                    "type": "pod_kill",
                    "target": {"namespace": "default", "label_selector": "app=api"},
                },
            ],
        }
    )
    metrics = FakeMetricsClient([0.1])
    result = run_experiment(exp, metrics, k8s, sleep=lambda s: None)

    assert result.partial_failure
    assert "no pods found matching 'app=missing'" in result.injection_error
    # action 1's effect is reported even though action 2 failed and action 3 never ran
    assert len(result.injections) == 1
    assert result.injections[0].action_type == "pod_kill"
    assert result.injections[0].description == "deleted 1 pod(s): api-1"
    assert k8s.deleted == [("default", "api-1")]
    assert result.post_check is None
    assert not result.passed


def test_records_wall_clock_timestamps(k8s):
    metrics = FakeMetricsClient([0.1, 0.2])
    ticks = iter([100.0, 110.0, 115.0, 130.0])  # start, inject, injected, done
    result = run_experiment(
        _experiment(), metrics, k8s, sleep=lambda s: None, clock=lambda: next(ticks)
    )

    assert result.started_at == 100.0
    assert result.injections[0].at == 110.0
    assert result.injection_finished_at == 115.0
    assert result.finished_at == 130.0
    assert result.duration_seconds == 30.0
    assert result.recovery_seconds == 15.0


def test_aborted_run_has_no_recovery_time(k8s):
    metrics = FakeMetricsClient([0.9])
    ticks = iter([50.0, 51.0])
    result = run_experiment(
        _experiment(), metrics, k8s, sleep=lambda s: None, clock=lambda: next(ticks)
    )

    assert result.aborted
    assert result.duration_seconds == 1.0
    assert result.injection_finished_at is None
    assert result.recovery_seconds is None


def _latency_experiment() -> object:
    return parse_experiment(
        {
            "name": "latency",
            "steady_state": [
                {"name": "p", "query": "q", "operator": "lt", "threshold": 1}
            ],
            "actions": [
                {
                    "type": "network_latency",
                    "target": {"namespace": "default", "label_selector": "app=api"},
                }
            ],
        }
    )


def test_interrupt_during_settle_removes_injected_faults(k8s):
    metrics = FakeMetricsClient([0.1])

    def interrupt(_seconds):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_experiment(_latency_experiment(), metrics, k8s, sleep=interrupt)

    # Both pods got the qdisc add exec, then a matching cleanup exec each.
    assert len(k8s.execs) == 4
    add_pods = {name for _, name, cmd in k8s.execs[:2]}
    cleanup_execs = k8s.execs[2:]
    assert {name for _, name, _ in cleanup_execs} == add_pods
    for _, _, command in cleanup_execs:
        assert "tc qdisc del" in " ".join(command)


def test_interrupt_during_post_check_removes_injected_faults(k8s):
    """A Ctrl-C while blocked on the final verify_steady_state call (e.g. a
    slow Prometheus post-check query) must still clean up injected faults,
    not just an interrupt during the settle sleep."""

    class InterruptingMetricsClient:
        def __init__(self, values):
            self._values = list(values)

        def query(self, promql: str) -> float:
            if not self._values:
                raise KeyboardInterrupt
            return self._values.pop(0)

    # Only the pre-check value is queued; the post-check query raises.
    metrics = InterruptingMetricsClient([0.1])

    with pytest.raises(KeyboardInterrupt):
        run_experiment(_latency_experiment(), metrics, k8s, sleep=lambda s: None)

    # Both pods got the qdisc add exec, then a matching cleanup exec each.
    assert len(k8s.execs) == 4
    add_pods = {name for _, name, cmd in k8s.execs[:2]}
    cleanup_execs = k8s.execs[2:]
    assert {name for _, name, _ in cleanup_execs} == add_pods
    for _, _, command in cleanup_execs:
        assert "tc qdisc del" in " ".join(command)


def test_interrupt_mid_injection_removes_faults_from_earlier_actions(k8s):
    class InterruptingKubernetesClient(FakeKubernetesClient):
        def delete_pod(self, namespace, name):
            raise KeyboardInterrupt

    exp = parse_experiment(
        {
            "name": "latency-then-kill",
            "steady_state": [
                {"name": "p", "query": "q", "operator": "lt", "threshold": 1}
            ],
            "actions": [
                {
                    "type": "network_latency",
                    "target": {"namespace": "default", "label_selector": "app=api"},
                },
                {
                    "type": "pod_kill",
                    "target": {"namespace": "default", "label_selector": "app=api"},
                },
            ],
        }
    )
    client = InterruptingKubernetesClient(
        {("default", "app=api"): ["api-1", "api-2"]}
    )
    metrics = FakeMetricsClient([0.1])

    with pytest.raises(KeyboardInterrupt):
        run_experiment(exp, metrics, client, sleep=lambda s: None)

    # The latency fault from action 1 is removed even though action 2
    # (pod_kill) is the one that raised.
    assert len(client.execs) == 4
    cleanup_execs = client.execs[2:]
    for _, _, command in cleanup_execs:
        assert "tc qdisc del" in " ".join(command)
