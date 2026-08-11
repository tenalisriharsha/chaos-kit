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
    at: float  # epoch timestamp of the injection


@dataclass
class RunResult:
    """The full outcome of running an experiment."""

    experiment: Experiment
    pre_check: list[ProbeResult]
    started_at: float = 0.0  # epoch timestamp
    injections: list[InjectionRecord] = field(default_factory=list)
    post_check: list[ProbeResult] | None = None
    aborted: bool = False
    injection_finished_at: float | None = None
    finished_at: float | None = None

    @property
    def passed(self) -> bool:
        """True when chaos was injected and the system recovered to steady."""
        return (
            not self.aborted
            and self.post_check is not None
            and all(r.passed for r in self.post_check)
        )

    @property
    def duration_seconds(self) -> float | None:
        """Wall-clock duration of the whole run, when it has finished."""
        if self.finished_at is None:
            return None
        return self.finished_at - self.started_at

    @property
    def recovery_seconds(self) -> float | None:
        """Seconds from end of injection to end of the post-check."""
        if self.finished_at is None or self.injection_finished_at is None:
            return None
        return self.finished_at - self.injection_finished_at


def run_experiment(
    experiment: Experiment,
    metrics: MetricsClient,
    kubernetes: KubernetesClient,
    settle_seconds: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> RunResult:
    """Run an experiment end to end and return its result.

    ``sleep`` is injectable so tests can skip the settle window; ``clock`` is
    injectable so tests can control the timestamps on the result.
    Raises ``InjectionError`` if an action cannot be injected.
    """
    pre_check = verify_steady_state(experiment.steady_state, metrics)
    result = RunResult(experiment=experiment, pre_check=pre_check, started_at=clock())

    if not all(r.passed for r in pre_check):
        result.aborted = True
        result.finished_at = clock()
        return result

    for action in experiment.actions:
        description = inject_action(action, kubernetes)
        result.injections.append(
            InjectionRecord(
                action_type=action.type,
                target=f"{action.target['namespace']}/{action.target['label_selector']}",
                description=description,
                at=clock(),
            )
        )

    result.injection_finished_at = clock()
    sleep(settle_seconds)
    result.post_check = verify_steady_state(experiment.steady_state, metrics)
    result.finished_at = clock()
    return result
