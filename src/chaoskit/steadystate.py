"""Steady-state hypothesis verification against Prometheus.

Before and after injecting chaos, every probe's PromQL query is evaluated
and compared against its threshold. The system is considered steady only
when all probes pass.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol, Sequence

from chaoskit.experiment import SteadyStateProbe


class SteadyStateError(RuntimeError):
    """Raised when a steady-state check cannot be performed."""


class MetricsClient(Protocol):
    """Anything that can resolve a PromQL query to a single float."""

    def query(self, promql: str) -> float: ...


class PrometheusClient:
    """Minimal instant-query client for the Prometheus HTTP API."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def query(self, promql: str) -> float:
        url = (
            f"{self.base_url}/api/v1/query?"
            + urllib.parse.urlencode({"query": promql})
        )
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except OSError as exc:
            raise SteadyStateError(f"prometheus query failed: {exc}") from exc
        except ValueError as exc:  # JSONDecodeError, UnicodeDecodeError
            raise SteadyStateError(
                f"prometheus returned a non-JSON response from {url}: {exc}"
            ) from exc

        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise SteadyStateError(f"prometheus returned an error: {payload!r}")
        result = payload.get("data", {}).get("result", [])
        if not result:
            raise SteadyStateError(f"query returned no data: {promql!r}")
        try:
            return float(result[0]["value"][1])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise SteadyStateError(
                f"unexpected prometheus result shape: {result[0]!r}"
            ) from exc


@dataclass(frozen=True)
class ProbeResult:
    probe: SteadyStateProbe
    value: float
    passed: bool


def verify_steady_state(
    probes: Sequence[SteadyStateProbe], client: MetricsClient
) -> list[ProbeResult]:
    """Evaluate every probe and return one result per probe."""
    results = []
    for probe in probes:
        value = client.query(probe.query)
        results.append(ProbeResult(probe=probe, value=value, passed=probe.evaluate(value)))
    return results


def all_passed(results: Sequence[ProbeResult]) -> bool:
    """True when every probe satisfied its expectation."""
    return all(r.passed for r in results)
