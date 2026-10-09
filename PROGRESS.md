# chaos-kit — Progress Log

STATUS: COMPLETE

## Vision

A declarative chaos engineering toolkit for Kubernetes. Users describe
resilience experiments in YAML (pod kill, CPU stress, network latency);
chaos-kit injects them, verifies the steady-state hypothesis with Prometheus
queries before and after injection, and produces a pass/fail resilience
report.

## Architecture

```
YAML experiment file
      |
      v
+------------------+     +---------------------+
| experiment.py    |     | steadystate.py      |
| schema +         |---->| PrometheusClient    |
| validation       |     | verify probes       |
+------------------+     +---------------------+
      |                          |
      v                          v
+------------------+     +---------------------+
| injectors/       |     | runner.py           |
| kubernetes chaos |---->| orchestrate:        |
| (pod_kill, ...)  |     | check -> inject ->  |
+------------------+     | wait -> check       |
                         +---------------------+
                                  |
                                  v
                         +---------------------+
                         | report.py           |
                         | pass/fail report    |
                         | (text + JSON)       |
                         +---------------------+
                                  |
                                  v
                           cli.py (chaoskit)
```

- `chaoskit.experiment` — parse/validate experiment YAML into typed models.
- `chaoskit.steadystate` — Prometheus instant queries, probe evaluation.
- `chaoskit.injectors` — Kubernetes chaos actions behind a mockable
  `KubernetesClient` protocol (pod_kill, cpu_stress, network_latency).
- `chaoskit.runner` — experiment orchestration: check -> inject -> settle ->
  re-check, with wall-clock timing (duration, recovery time).
- `chaoskit.report` — resilience report rendering (text + JSON).
- `chaoskit.cli` — `validate`, `check`, `run` subcommands (`run --json`).

## Build plan

### Phase 1 — Foundation ✅ (done, night 1)
- [x] Project scaffold (pyproject, src layout, venv, git)
- [x] Experiment schema: YAML loading + validation with full error reporting
- [x] Steady-state verification: Prometheus client + probe evaluation
- [x] CLI: `validate` and `check` subcommands
- [x] Tests for all of the above (35 passing)

### Phase 2 — Injection & orchestration ✅ (done, night 2)
- [x] `injectors/` package: Kubernetes client abstraction (mockable)
- [x] `pod_kill` injector (delete pods matching label_selector)
- [x] `cpu_stress` and `network_latency` injectors
- [x] `runner.py`: check steady state -> inject -> settle window -> re-check
- [x] CLI `run` subcommand wiring it together
- [x] Tests with a fake Kubernetes client (60 passing total)

### Phase 3 — Reporting & polish ✅ (done, night 3)
- [x] Wall-clock timestamps in the runner (`started_at`, per-injection `at`,
  `injection_finished_at`, `finished_at`; injectable `clock` for tests)
- [x] `report.py`: pass/fail resilience report as text and JSON
  (`render_text`, `render_json`, `report_dict`)
- [x] Duration/recovery-time metrics in the report
- [x] `chaoskit run --json` for machine-readable output
- [x] Examples gallery (`cpu-stress.yaml`, `network-latency.yaml`) and
  sample report output in the README
- [x] Tests for all of the above (70 passing total)

## Project complete

All three phases are done, the full suite passes
(`.venv/bin/python -m pytest` -> 70 passed at the end of phase 3; 85 after
the post-review error-handling fixes, now run by CI on Python 3.10-3.13),
the README is final, and
[DAILY_REPORT.md](DAILY_REPORT.md) summarizes the whole build.

Possible future ideas (not planned): experiment scheduling/rollbacks,
a `diff` command comparing reports across runs, custom probe operators,
Grafana/Slack report export.
