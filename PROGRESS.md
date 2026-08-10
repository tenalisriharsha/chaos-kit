# chaos-kit — Progress Log

STATUS: IN_PROGRESS

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
- `chaoskit.runner` — experiment orchestration: check -> inject -> settle -> re-check.
- `chaoskit.report` — resilience report generation (Phase 3).
- `chaoskit.cli` — `validate`, `check`, `run` subcommands.

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

### Phase 3 — Reporting & polish (next)
- [ ] `report.py`: pass/fail resilience report (text + `--json` output)
- [ ] Duration/recovery-time metrics in the report
- [ ] Example experiments gallery, README screenshots/output samples

## Resume here (night 3)

Phase 2 is complete and green (`.venv/bin/python -m pytest` -> 60 passed).
Tomorrow: start Phase 3 with `src/chaoskit/report.py` — take the runner's
`RunResult` (in `src/chaoskit/runner.py`) and render a pass/fail resilience
report as text, plus machine-readable JSON behind a `--json` flag on
`chaoskit run` (see `cmd_run` in `src/chaoskit/cli.py`). Add wall-clock
timestamps around injection in the runner so the report can show duration
and recovery time. Then add an examples gallery under `examples/` and
sample report output in the README. Finish with DAILY_REPORT.md.
