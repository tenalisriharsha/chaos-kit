"""Tests for steady-state verification."""

import pytest

from chaoskit.experiment import SteadyStateProbe
from chaoskit.steadystate import (
    PrometheusClient,
    SteadyStateError,
    all_passed,
    verify_steady_state,
)


class FakeClient:
    def __init__(self, values):
        self.values = values
        self.queries = []

    def query(self, promql):
        self.queries.append(promql)
        return self.values[promql]


PROBES = [
    SteadyStateProbe(name="errors", query="rate(errors[5m])", operator="lt", threshold=0.01),
    SteadyStateProbe(name="latency", query="p99", operator="lte", threshold=0.5),
]


def test_verify_all_pass():
    client = FakeClient({"rate(errors[5m])": 0.001, "p99": 0.2})
    results = verify_steady_state(PROBES, client)
    assert all_passed(results)
    assert [r.passed for r in results] == [True, True]
    assert client.queries == ["rate(errors[5m])", "p99"]


def test_verify_detects_violation():
    client = FakeClient({"rate(errors[5m])": 0.5, "p99": 0.2})
    results = verify_steady_state(PROBES, client)
    assert not all_passed(results)
    assert results[0].passed is False
    assert results[0].value == 0.5
    assert results[1].passed is True


def test_results_preserve_probe_order():
    client = FakeClient({"rate(errors[5m])": 0.0, "p99": 0.0})
    results = verify_steady_state(PROBES, client)
    assert [r.probe.name for r in results] == ["errors", "latency"]


def test_prometheus_client_parses_response(prometheus):
    prometheus.respond_value(0.0042)
    client = PrometheusClient(prometheus.url)
    assert client.query("up") == pytest.approx(0.0042)
    assert prometheus.queries == ["up"]


def test_prometheus_client_empty_result(prometheus):
    prometheus.respond({"status": "success", "data": {"result": []}})
    client = PrometheusClient(prometheus.url)
    with pytest.raises(SteadyStateError, match="no data"):
        client.query("up")


def test_prometheus_client_error_status(prometheus):
    prometheus.respond({"status": "error", "error": "parse error"})
    client = PrometheusClient(prometheus.url)
    with pytest.raises(SteadyStateError, match="error"):
        client.query("up")


def test_prometheus_client_unreachable():
    client = PrometheusClient("http://127.0.0.1:1", timeout=0.5)
    with pytest.raises(SteadyStateError, match="failed"):
        client.query("up")
