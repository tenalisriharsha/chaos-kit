"""Tests for the resilience report renderers (text and JSON)."""

import json

import pytest

from chaoskit.experiment import parse_experiment
from chaoskit.report import render_json, render_text, report_dict
from chaoskit.runner import RunResult, run_experiment

from fakes import FakeKubernetesClient


class FakeMetricsClient:
    """Serves queued query results, one per call."""

    def __init__(self, values: list[float]):
        self._values = list(values)

    def query(self, promql: str) -> float:
        return self._values.pop(0)


def _experiment() -> object:
    return parse_experiment(
        {
            "name": "demo",
            "description": "demo experiment",
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
                }
            ],
        }
    )


@pytest.fixture
def k8s():
    return FakeKubernetesClient({("default", "app=api"): ["api-1", "api-2"]})


def _run(metrics_values, k8s):
    ticks = iter([100.0, 110.0, 115.0, 130.0])
    return run_experiment(
        _experiment(),
        FakeMetricsClient(metrics_values),
        k8s,
        sleep=lambda s: None,
        clock=lambda: next(ticks),
    )


def test_text_report_passed(k8s):
    text = render_text(_run([0.1, 0.2], k8s))

    assert "chaos-kit resilience report" in text
    assert "Experiment: demo" in text
    assert "demo experiment" in text
    assert "Started:  1970-01-01T00:01:40Z" in text  # epoch 100
    assert "Duration: 30.00s (recovery: 15.00s)" in text
    assert "PASS low-errors: value=0.1 (expected lt 0.5)" in text
    assert "PASS low-errors: value=0.2 (expected lt 0.5)" in text
    assert "pod_kill -> default/app=api" in text
    assert "deleted 1 pod(s): api-1" in text
    assert "Verdict: experiment PASSED" in text


def test_text_report_failed(k8s):
    text = render_text(_run([0.1, 0.9], k8s))

    assert "FAIL low-errors: value=0.9 (expected lt 0.5)" in text
    assert "experiment FAILED" in text


def test_text_report_aborted(k8s):
    ticks = iter([50.0, 51.0])
    result = run_experiment(
        _experiment(),
        FakeMetricsClient([0.9]),
        k8s,
        sleep=lambda s: None,
        clock=lambda: next(ticks),
    )
    text = render_text(result)

    assert "Pre-injection steady state:" in text
    assert "Injected chaos:" not in text
    assert "Post-injection steady state:" not in text
    assert "experiment ABORTED" in text
    assert "recovery: -" in text


def test_json_report_structure(k8s):
    result = _run([0.1, 0.2], k8s)
    data = json.loads(render_json(result))

    assert data["experiment"] == {"name": "demo", "description": "demo experiment"}
    assert data["verdict"] == "passed"
    assert data["passed"] is True
    assert data["started_at"] == 100.0
    assert data["finished_at"] == 130.0
    assert data["duration_seconds"] == 30.0
    assert data["recovery_seconds"] == 15.0
    assert data["steady_state"]["pre"] == [
        {
            "name": "low-errors",
            "query": "error_rate",
            "operator": "lt",
            "threshold": 0.5,
            "value": 0.1,
            "passed": True,
        }
    ]
    assert data["steady_state"]["post"][0]["value"] == 0.2
    assert data["injections"] == [
        {
            "type": "pod_kill",
            "target": "default/app=api",
            "description": "deleted 1 pod(s): api-1",
            "at": 110.0,
        }
    ]


def test_json_report_aborted_has_null_post_check(k8s):
    ticks = iter([50.0, 51.0])
    result = run_experiment(
        _experiment(),
        FakeMetricsClient([0.9]),
        k8s,
        sleep=lambda s: None,
        clock=lambda: next(ticks),
    )
    data = json.loads(render_json(result))

    assert data["verdict"] == "aborted"
    assert data["passed"] is False
    assert data["steady_state"]["post"] is None
    assert data["injections"] == []
    assert data["recovery_seconds"] is None


def test_report_dict_on_empty_result():
    """A result that never ran still renders (defensive defaults)."""
    exp = _experiment()
    result = RunResult(experiment=exp, pre_check=[])
    data = report_dict(result)

    assert data["verdict"] == "failed"
    assert data["duration_seconds"] is None
    assert render_text(result).endswith(
        "experiment FAILED (steady state violated after injection)"
    )
