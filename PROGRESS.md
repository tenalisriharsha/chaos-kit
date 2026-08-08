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
- `chaoskit.injectors` — Kubernetes chaos actions (Phase 2).
- `chaoskit.runner` — experiment orchestration (Phase 2).
- `chaoskit.report` — resilience report generation (Phase 3).
- `chaoskit.cli` — `validate`, `check`, `run` subcommands.

## Build plan

### Phase 1 — Foundation ✅ (done, night 1)
- [x] Project scaffold (pyproject, src layout, venv, git)
- [x] Experiment schema: YAML loading + validation with full error reporting
- [x] Steady-state verification: Prometheus client + probe evaluation
- [x] CLI: `validate` and `check` subcommands
- [x] Tests for all of the above (35 passing)

### Phase 2 — Injection & orchestration (next)
- [ ] `injectors/` package: Kubernetes client abstraction (mockable)
- [ ] `pod_kill` injector (delete pods matching label_selector)
- [ ] `cpu_stress` and `network_latency` injectors
- [ ] `runner.py`: check steady state -> inject -> settle window -> re-check
- [ ] CLI `run` subcommand wiring it together
- [ ] Tests with a fake Kubernetes client

### Phase 3 — Reporting & polish
- [ ] `report.py`: pass/fail resilience report (text + `--json` output)
- [ ] Duration/recovery-time metrics in the report
- [ ] Example experiments gallery, README screenshots/output samples

## Resume here (night 2)

Phase 1 is complete and green (`.venv/bin/python -m pytest` -> 35 passed).
Tomorrow: start Phase 2 at the injectors — create `src/chaoskit/injectors/`
with a `KubernetesClient` protocol and the `pod_kill` injector first
(delete pods matching `target.namespace` + `target.label_selector`, honoring
`params.count`), then `runner.py` (steady-state check -> inject -> settle ->
re-check) and the `run` CLI subcommand. Add tests with a fake k8s client;
keep the real kubernetes dependency optional/lazy so tests don't need a
cluster.
