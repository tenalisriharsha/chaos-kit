"""Experiment orchestration: check -> inject -> settle -> re-check.

The runner verifies the steady-state hypothesis, injects every chaos action
in order, waits for a settle window, then verifies the hypothesis again.
If the system is not steady before injection, the experiment aborts without
injecting anything.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from chaoskit.experiment import Experiment
from chaoskit.injectors import inject_action
from chaoskit.injectors.kubernetes import KubernetesClient
from chaoskit.steadystate import MetricsClient, ProbeResult, verify_steady_state


@dataclass(frozen=True)
class InjectionRecord:
    """One injected action and its human-readable outcome."""

    action_type: str
    target: str
    description: str


@dataclass
class RunResult:
    """The full outcome of running an experiment."""

    experiment: Experiment
    pre_check: list[ProbeResult]
    injections: list[InjectionRecord] = field(default_factory=list)
    post_check: list[ProbeResult] | None = None
    aborted: bool = False

    @property
    def passed(self) -> bool:
        """True when chaos was injected and the system recovered to steady."""
        return (
            not self.aborted
            and self.post_check is not None
            and all(r.passed for r in self.post_check)
        )


def run_experiment(
    experiment: Experiment,
    metrics: MetricsClient,
    kubernetes: KubernetesClient,
    settle_seconds: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
) -> RunResult:
    """Run an experiment end to end and return its result.

    ``sleep`` is injectable so tests can skip the settle window.
    Raises ``InjectionError`` if an action cannot be injected.
    """
    pre_check = verify_steady_state(experiment.steady_state, metrics)
    result = RunResult(experiment=experiment, pre_check=pre_check)

    if not all(r.passed for r in pre_check):
        result.aborted = True
        return result

    for action in experiment.actions:
        description = inject_action(action, kubernetes)
        result.injections.append(
            InjectionRecord(
                action_type=action.type,
                target=f"{action.target['namespace']}/{action.target['label_selector']}",
                description=description,
            )
        )

    sleep(settle_seconds)
    result.post_check = verify_steady_state(experiment.steady_state, metrics)
    return result
