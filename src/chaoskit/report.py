"""Resilience report generation.

Renders a runner ``RunResult`` as a human-readable text report or as
machine-readable JSON (``chaoskit run --json``). The report covers the
verdict, pre/post steady-state probes, injected actions, and wall-clock
timing (total duration and recovery time).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from chaoskit.runner import RunResult
from chaoskit.steadystate import ProbeResult


def _iso(ts: float | None) -> str:
    """Format an epoch timestamp as UTC ISO-8601, or '-' when missing."""
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}s"


def _verdict(result: RunResult) -> str:
    if result.aborted:
        return "aborted"
    return "passed" if result.passed else "failed"


def _verdict_line(result: RunResult) -> str:
    if result.aborted:
        return "experiment ABORTED (steady state violated before injection)"
    if result.passed:
        return "experiment PASSED"
    return "experiment FAILED (steady state violated after injection)"


def _probe_line(result: ProbeResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    probe = result.probe
    return (
        f"  {status} {probe.name}: value={result.value} "
        f"(expected {probe.operator} {probe.threshold})"
    )


def render_text(result: RunResult) -> str:
    """Render a human-readable resilience report."""
    exp = result.experiment
    lines = [
        "chaos-kit resilience report",
        "===========================",
        f"Experiment: {exp.name}",
    ]
    if exp.description:
        lines.append(f"  {exp.description}")
    lines.append(f"Started:  {_iso(result.started_at)}")
    lines.append(
        f"Duration: {_seconds(result.duration_seconds)}"
        f" (recovery: {_seconds(result.recovery_seconds)})"
    )

    lines.append("")
    lines.append("Pre-injection steady state:")
    lines.extend(_probe_line(r) for r in result.pre_check)

    if not result.aborted:
        lines.append("")
        lines.append("Injected chaos:")
        for record in result.injections:
            lines.append(
                f"  - {record.action_type} -> {record.target}: "
                f"{record.description} (at {_iso(record.at)})"
            )
        lines.append("")
        lines.append("Post-injection steady state:")
        lines.extend(_probe_line(r) for r in result.post_check or [])

    lines.append("")
    lines.append(f"Verdict: {_verdict_line(result)}")
    return "\n".join(lines)


def report_dict(result: RunResult) -> dict:
    """Build the machine-readable report as a plain dict."""
    exp = result.experiment
    return {
        "experiment": {"name": exp.name, "description": exp.description},
        "verdict": _verdict(result),
        "passed": result.passed,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "duration_seconds": result.duration_seconds,
        "recovery_seconds": result.recovery_seconds,
        "steady_state": {
            "pre": [_probe_dict(r) for r in result.pre_check],
            "post": (
                [_probe_dict(r) for r in result.post_check]
                if result.post_check is not None
                else None
            ),
        },
        "injections": [
            {
                "type": record.action_type,
                "target": record.target,
                "description": record.description,
                "at": record.at,
            }
            for record in result.injections
        ],
    }


def _probe_dict(result: ProbeResult) -> dict:
    probe = result.probe
    return {
        "name": probe.name,
        "query": probe.query,
        "operator": probe.operator,
        "threshold": probe.threshold,
        "value": result.value,
        "passed": result.passed,
    }


def render_json(result: RunResult) -> str:
    """Render the resilience report as pretty-printed JSON."""
    return json.dumps(report_dict(result), indent=2)
