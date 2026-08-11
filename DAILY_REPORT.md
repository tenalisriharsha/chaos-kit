# chaos-kit — Daily Report

**Status: COMPLETE** — built over 3 nights, 70 tests passing.

## What was built

A declarative chaos engineering toolkit for Kubernetes. Experiments are
described in YAML — a steady-state hypothesis (PromQL queries with
thresholds) plus a list of chaos actions — and chaos-kit runs them end to
end: verify steady state, inject chaos, wait out a settle window, verify
again, and emit a pass/fail resilience report.

### Night 1 — Foundation (Phase 1)
- Project scaffold: `pyproject.toml`, `src/` layout, editable install,
  pytest setup.
- `chaoskit.experiment`: YAML loading and full validation with all errors
  reported in one pass; typed models (`Experiment`, `SteadyStateProbe`,
  `Action`) and six comparison operators.
- `chaoskit.steadystate`: minimal Prometheus instant-query HTTP client and
  probe evaluation against thresholds.
- `chaoskit.cli`: `validate` and `check` subcommands.
- 35 tests, including a stub Prometheus HTTP server fixture.

### Night 2 — Injection & orchestration (Phase 2)
- `chaoskit.injectors`: a mockable `KubernetesClient` protocol plus a real
  `CoreV1KubernetesClient` (lazy `kubernetes` package import).
- Three chaos actions: `pod_kill` (delete matching pods), `cpu_stress`
  (`stress-ng` via exec), `network_latency` (self-cleaning `tc`/netem).
- `chaoskit.runner`: check -> inject -> settle -> re-check orchestration;
  aborts without injecting anything when the pre-check fails.
- `chaoskit run` CLI subcommand.
- 25 more tests (60 total) with a fake in-memory Kubernetes client.

### Night 3 — Reporting & polish (Phase 3)
- Wall-clock timing in the runner: `started_at`, per-injection timestamps,
  `injection_finished_at`, `finished_at`, with `duration_seconds` and
  `recovery_seconds` derived properties (injectable `clock` for tests).
- `chaoskit.report`: text and JSON renderers for the resilience report —
  verdict, pre/post probe results, injected actions, and timings.
- `chaoskit run --json` for machine-readable output; exit codes 0/1/2 for
  passed / failed-or-aborted / setup error.
- Examples gallery: `cpu-stress.yaml` and `network-latency.yaml` alongside
  the original multi-action `experiment.yaml`.
- README updated with the gallery and a sample report.
- 10 more tests (70 total).

## Test results

```
.venv/bin/python -m pytest -q
70 passed in ~5s
```

Coverage spans: schema validation, Prometheus client (success, error, empty
and malformed responses), probe evaluation, all three injectors, runner
orchestration (happy path, abort, no-recovery, action ordering, timing),
both report renderers, and every CLI subcommand.

## Known limitations

- Chaos actions other than `pod_kill` require tooling inside the target
  containers (`stress-ng` for `cpu_stress`; `tc` plus `NET_ADMIN` for
  `network_latency`).
- Steady-state checks use Prometheus instant queries only — no range
  queries or alert-rule integration.
- The runner is sequential: one experiment, actions in order, single
  settle window. No scheduling, parallelism, or rollback actions.
- Reports go to stdout only; no persistence or export (Slack, Grafana).
- The real Kubernetes path is covered by unit tests against a fake client;
  it has not been run against a live cluster in this repo.

## Future ideas

- Scheduled/continuous experiments and a report store with run history.
- A `diff` command comparing resilience reports across runs.
- Custom probe operators and templated experiment parameters.
- Report exporters (JSON file, Slack, Grafana annotations).
- More injectors: disk fill, DNS sabotage, node drain.
