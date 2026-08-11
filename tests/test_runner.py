"""Tests for the experiment runner's orchestration flow."""

import pytest

from chaoskit.experiment import parse_experiment
from chaoskit.injectors import InjectionError
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


def test_injection_error_propagates():
    metrics = FakeMetricsClient([0.1])
    with pytest.raises(InjectionError, match="no pods found"):
        run_experiment(
            _experiment(), metrics, FakeKubernetesClient(), sleep=lambda s: None
        )


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
