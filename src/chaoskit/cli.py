"""Command-line interface for chaos-kit."""

from __future__ import annotations

import argparse
import sys

from chaoskit.experiment import ExperimentError, load_experiment
from chaoskit.steadystate import (
    PrometheusClient,
    SteadyStateError,
    all_passed,
    verify_steady_state,
)


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

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        probe = result.probe
        print(
            f"{status} {probe.name}: value={result.value} "
            f"(expected {probe.operator} {probe.threshold})"
        )
    if all_passed(results):
        print("Steady state: OK")
        return 0
    print("Steady state: VIOLATED")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"validate": cmd_validate, "check": cmd_check}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
