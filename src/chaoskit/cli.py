"""Command-line interface for chaos-kit."""

from __future__ import annotations

import argparse
import math
import sys

from chaoskit.experiment import ExperimentError, load_experiment
from chaoskit.injectors import InjectionError
from chaoskit.injectors.kubernetes import KubernetesError
from chaoskit import report
from chaoskit.runner import run_experiment
from chaoskit.steadystate import (
    PrometheusClient,
    SteadyStateError,
    all_passed,
    verify_steady_state,
)


def _settle_seconds(value: str) -> float:
    """argparse type for --settle: a finite number of seconds >= 0.

    Validated up front because the runner only sleeps after chaos has been
    injected; a bad value must not crash the run at that point.
    """
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
    if not math.isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError(
            f"must be a finite number of seconds >= 0, got {value!r}"
        )
    return seconds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chaoskit",
        description="Declarative chaos engineering toolkit for Kubernetes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser(
        "validate", help="Validate an experiment YAML file and print a summary."
    )
    p_validate.add_argument("file", help="Path to the experiment YAML file.")

    p_check = sub.add_parser(
        "check",
        help="Run the steady-state checks of an experiment against Prometheus.",
    )
    p_check.add_argument("file", help="Path to the experiment YAML file.")
    p_check.add_argument(
        "--prometheus",
        default="http://localhost:9090",
        help="Prometheus base URL (default: http://localhost:9090).",
    )

    p_run = sub.add_parser(
        "run",
        help="Run an experiment: steady-state check, inject chaos, re-check.",
    )
    p_run.add_argument("file", help="Path to the experiment YAML file.")
    p_run.add_argument(
        "--prometheus",
        default="http://localhost:9090",
        help="Prometheus base URL (default: http://localhost:9090).",
    )
    p_run.add_argument(
        "--settle",
        type=_settle_seconds,
        default=10.0,
        help="Seconds to wait after injection before re-checking (default: 10).",
    )
    p_run.add_argument(
        "--json",
        action="store_true",
        help="Print the resilience report as JSON instead of text.",
    )
    return parser


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        exp = load_experiment(args.file)
    except ExperimentError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    print(f"Experiment: {exp.name}")
    if exp.description:
        print(f"  {exp.description}")
    print(f"Steady-state probes: {len(exp.steady_state)}")
    for probe in exp.steady_state:
        print(f"  - {probe.name}: {probe.query} {probe.operator} {probe.threshold}")
    print(f"Actions: {len(exp.actions)}")
    for action in exp.actions:
        print(f"  - {action.type} -> {action.target.get('namespace')}"
              f"/{action.target.get('label_selector')}")
    print("OK: experiment definition is valid")
    return 0


def _print_probe_results(results: list) -> None:
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        probe = result.probe
        print(
            f"{status} {probe.name}: value={result.value} "
            f"(expected {probe.operator} {probe.threshold})"
        )


def _build_kubernetes_client():
    """Construct the real Kubernetes client (lazy, monkeypatchable)."""
    from chaoskit.injectors.kubernetes import CoreV1KubernetesClient

    return CoreV1KubernetesClient()


def cmd_check(args: argparse.Namespace) -> int:
    try:
        exp = load_experiment(args.file)
    except ExperimentError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2

    client = PrometheusClient(args.prometheus)
    try:
        results = verify_steady_state(exp.steady_state, client)
    except SteadyStateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    _print_probe_results(results)
    if all_passed(results):
        print("Steady state: OK")
        return 0
    print("Steady state: VIOLATED")
    return 1


def cmd_run(args: argparse.Namespace) -> int:
    try:
        exp = load_experiment(args.file)
    except ExperimentError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2

    try:
        kubernetes = _build_kubernetes_client()
    except KubernetesError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    metrics = PrometheusClient(args.prometheus)
    try:
        result = run_experiment(exp, metrics, kubernetes, settle_seconds=args.settle)
    except (SteadyStateError, InjectionError, KubernetesError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(report.render_json(result))
    else:
        print(report.render_text(result))

    if result.passed:
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"validate": cmd_validate, "check": cmd_check, "run": cmd_run}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
