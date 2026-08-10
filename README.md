# chaos-kit

A declarative chaos engineering toolkit for Kubernetes.

Define resilience experiments in YAML — pod kills, CPU stress, network
latency — and chaos-kit injects them, verifies your steady-state hypothesis
against Prometheus before and after, and produces a pass/fail resilience
report.

## Project Status

**Active development** — built in public, nightly progress.
See [PROGRESS.md](PROGRESS.md) for the vision, architecture, phased build
plan, and exactly where the build currently stands.

Current state: **Phase 2 complete** — experiment schema, steady-state
verification against Prometheus, Kubernetes chaos injectors (`pod_kill`,
`cpu_stress`, `network_latency`), an experiment runner, and a CLI
(`validate`, `check`, `run`), fully tested. Resilience reports land in
Phase 3.

## Experiment format

```yaml
name: api-pod-kill-resilience
description: Kill one API pod and verify the service stays healthy.

steady_state:
  - name: low-error-rate
    query: rate(http_requests_total{status=~"5.."}[5m])
    operator: lt
    threshold: 0.01

actions:
  - type: pod_kill
    target:
      namespace: default
      label_selector: app=api
    params:
      count: 1
```

See [examples/experiment.yaml](examples/experiment.yaml) for a full example.

## Usage

```bash
# Validate an experiment definition
chaoskit validate examples/experiment.yaml

# Check the steady-state hypothesis against Prometheus
chaoskit check examples/experiment.yaml --prometheus http://localhost:9090

# Run the full experiment: steady-state check, inject chaos, settle, re-check
chaoskit run examples/experiment.yaml --prometheus http://localhost:9090
```

## Chaos actions

| Action | Effect | Params (defaults) |
| --- | --- | --- |
| `pod_kill` | Deletes pods matching the target selector | `count` (1) |
| `cpu_stress` | Runs `stress-ng` inside matching pods | `cores` (1), `duration` (30s) |
| `network_latency` | Adds egress latency via `tc`/netem, self-cleaning | `latency_ms` (100), `duration` (30s) |

Actions target pods via `target.namespace` and `target.label_selector`.
`cpu_stress` needs `stress-ng` in the container image; `network_latency`
needs `tc` (iproute2) and the `NET_ADMIN` capability.

`chaoskit run` requires a kubeconfig (or in-cluster config) and the optional
`kubernetes` Python package (`pip install kubernetes`). It verifies the
steady-state hypothesis first and aborts without injecting anything if the
system is already unhealthy.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

## License

MIT
