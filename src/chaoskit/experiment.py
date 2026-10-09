"""Experiment definition loading and validation.

An experiment is a YAML document describing a steady-state hypothesis
(Prometheus queries with expected thresholds) and a list of chaos actions
to inject into a Kubernetes cluster.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

COMPARATORS = {
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
    "eq": operator.eq,
    "neq": operator.ne,
}

SUPPORTED_ACTIONS = ("pod_kill", "cpu_stress", "network_latency")


class ExperimentError(ValueError):
    """Raised when an experiment definition is missing or invalid."""


@dataclass(frozen=True)
class SteadyStateProbe:
    """A Prometheus query plus an expectation on its result."""

    name: str
    query: str
    operator: str
    threshold: float

    def evaluate(self, value: float) -> bool:
        """Return True when the observed value satisfies the expectation."""
        return COMPARATORS[self.operator](value, self.threshold)


@dataclass(frozen=True)
class Action:
    """A single chaos action to inject."""

    type: str
    target: dict[str, str]
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Experiment:
    """A fully parsed and validated experiment definition."""

    name: str
    description: str
    steady_state: tuple[SteadyStateProbe, ...]
    actions: tuple[Action, ...]


def load_experiment(path: str | Path) -> Experiment:
    """Load and validate an experiment from a YAML file."""
    p = Path(path)
    if not p.is_file():
        raise ExperimentError(f"experiment file not found: {p}")
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ExperimentError(f"cannot read experiment file {p}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ExperimentError(f"invalid YAML in {p}: {exc}") from exc
    return parse_experiment(data)


def parse_experiment(data: Any) -> Experiment:
    """Validate raw parsed YAML and build an Experiment.

    Collects all validation problems before raising, so users see every
    error in one pass instead of fixing them one at a time.
    """
    if not isinstance(data, dict):
        raise ExperimentError("experiment file must contain a YAML mapping")

    errors: list[str] = []

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("'name' is required and must be a non-empty string")

    description = data.get("description", "")
    if not isinstance(description, str):
        errors.append("'description' must be a string")
        description = ""

    probes = _parse_probes(data.get("steady_state"), errors)
    actions = _parse_actions(data.get("actions"), errors)

    if errors:
        raise ExperimentError("invalid experiment:\n- " + "\n- ".join(errors))

    return Experiment(
        name=name.strip(),
        description=description,
        steady_state=tuple(probes),
        actions=tuple(actions),
    )


def _parse_probes(raw: Any, errors: list[str]) -> list[SteadyStateProbe]:
    if not isinstance(raw, list) or not raw:
        errors.append("'steady_state' is required and must be a non-empty list")
        return []

    probes: list[SteadyStateProbe] = []
    for i, item in enumerate(raw):
        prefix = f"steady_state[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be a mapping")
            continue

        probe_name = item.get("name")
        query = item.get("query")
        op = item.get("operator")
        threshold = item.get("threshold")

        ok = True
        if not isinstance(probe_name, str) or not probe_name.strip():
            errors.append(f"{prefix}.name: required non-empty string")
            ok = False
        if not isinstance(query, str) or not query.strip():
            errors.append(f"{prefix}.query: required non-empty PromQL string")
            ok = False
        if op not in COMPARATORS:
            errors.append(
                f"{prefix}.operator: must be one of {sorted(COMPARATORS)}, got {op!r}"
            )
            ok = False
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            errors.append(f"{prefix}.threshold: required number")
            ok = False

        if ok:
            probes.append(
                SteadyStateProbe(
                    name=probe_name.strip(),
                    query=query.strip(),
                    operator=op,
                    threshold=float(threshold),
                )
            )
    return probes


def _parse_actions(raw: Any, errors: list[str]) -> list[Action]:
    if not isinstance(raw, list) or not raw:
        errors.append("'actions' is required and must be a non-empty list")
        return []

    actions: list[Action] = []
    for i, item in enumerate(raw):
        prefix = f"actions[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be a mapping")
            continue

        action_type = item.get("type")
        target = item.get("target")
        params = item.get("params", {})

        ok = True
        if action_type not in SUPPORTED_ACTIONS:
            errors.append(
                f"{prefix}.type: must be one of {list(SUPPORTED_ACTIONS)}, got {action_type!r}"
            )
            ok = False
        if not isinstance(target, dict):
            errors.append(f"{prefix}.target: required mapping")
            ok = False
        elif not isinstance(target.get("label_selector"), str) or not target.get(
            "label_selector"
        ).strip():
            errors.append(f"{prefix}.target.label_selector: required non-empty string")
            ok = False
        elif "namespace" in target and (
            not isinstance(target["namespace"], str) or not target["namespace"].strip()
        ):
            errors.append(f"{prefix}.target.namespace: must be a non-empty string")
            ok = False
        if not isinstance(params, dict):
            errors.append(f"{prefix}.params: must be a mapping")
            ok = False

        if ok:
            target = dict(target)
            target.setdefault("namespace", "default")
            actions.append(Action(type=action_type, target=target, params=dict(params)))
    return actions
