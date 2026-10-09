"""Tests for experiment loading and validation."""

import pytest

from chaoskit.experiment import (
    ExperimentError,
    SteadyStateProbe,
    load_experiment,
    parse_experiment,
)

VALID = {
    "name": "demo",
    "description": "a demo experiment",
    "steady_state": [
        {
            "name": "errors",
            "query": "rate(errors[5m])",
            "operator": "lt",
            "threshold": 0.01,
        }
    ],
    "actions": [
        {
            "type": "pod_kill",
            "target": {"namespace": "apps", "label_selector": "app=api"},
            "params": {"count": 1},
        }
    ],
}


def test_parse_valid_experiment():
    exp = parse_experiment(VALID)
    assert exp.name == "demo"
    assert exp.description == "a demo experiment"
    assert len(exp.steady_state) == 1
    assert exp.steady_state[0].name == "errors"
    assert len(exp.actions) == 1
    assert exp.actions[0].type == "pod_kill"
    assert exp.actions[0].target["namespace"] == "apps"
    assert exp.actions[0].params == {"count": 1}


def test_namespace_defaults_to_default():
    data = {
        **VALID,
        "actions": [
            {"type": "pod_kill", "target": {"label_selector": "app=api"}}
        ],
    }
    exp = parse_experiment(data)
    assert exp.actions[0].target["namespace"] == "default"


def test_description_optional():
    data = {k: v for k, v in VALID.items() if k != "description"}
    exp = parse_experiment(data)
    assert exp.description == ""


@pytest.mark.parametrize("operator", ["lt", "lte", "gt", "gte", "eq", "neq"])
def test_all_operators_accepted(operator):
    data = {
        **VALID,
        "steady_state": [
            {"name": "p", "query": "up", "operator": operator, "threshold": 1}
        ],
    }
    exp = parse_experiment(data)
    assert exp.steady_state[0].operator == operator


def test_probe_evaluate():
    probe = SteadyStateProbe(name="p", query="up", operator="lt", threshold=1.0)
    assert probe.evaluate(0.5)
    assert not probe.evaluate(1.0)
    assert not probe.evaluate(2.0)


def test_top_level_must_be_mapping():
    with pytest.raises(ExperimentError, match="YAML mapping"):
        parse_experiment(["not", "a", "mapping"])


def test_missing_name():
    data = {k: v for k, v in VALID.items() if k != "name"}
    with pytest.raises(ExperimentError, match="'name' is required"):
        parse_experiment(data)


def test_empty_steady_state_rejected():
    with pytest.raises(ExperimentError, match="steady_state"):
        parse_experiment({**VALID, "steady_state": []})


def test_empty_actions_rejected():
    with pytest.raises(ExperimentError, match="actions"):
        parse_experiment({**VALID, "actions": []})


def test_unknown_operator_rejected():
    data = {
        **VALID,
        "steady_state": [
            {"name": "p", "query": "up", "operator": "approx", "threshold": 1}
        ],
    }
    with pytest.raises(ExperimentError, match="operator"):
        parse_experiment(data)


def test_non_numeric_threshold_rejected():
    data = {
        **VALID,
        "steady_state": [
            {"name": "p", "query": "up", "operator": "lt", "threshold": "low"}
        ],
    }
    with pytest.raises(ExperimentError, match="threshold"):
        parse_experiment(data)


def test_unknown_action_type_rejected():
    data = {
        **VALID,
        "actions": [
            {"type": "delete_cluster", "target": {"label_selector": "app=api"}}
        ],
    }
    with pytest.raises(ExperimentError, match="pod_kill"):
        parse_experiment(data)


def test_action_requires_label_selector():
    data = {**VALID, "actions": [{"type": "pod_kill", "target": {}}]}
    with pytest.raises(ExperimentError, match="label_selector"):
        parse_experiment(data)


def test_multiple_errors_reported_together():
    data = {"steady_state": [], "actions": [{"type": "nope"}]}
    with pytest.raises(ExperimentError) as excinfo:
        parse_experiment(data)
    message = str(excinfo.value)
    assert "'name' is required" in message
    assert "steady_state" in message
    assert "actions[0].type" in message


def test_load_experiment_from_file(tmp_path):
    import yaml

    path = tmp_path / "exp.yaml"
    path.write_text(yaml.safe_dump(VALID))
    exp = load_experiment(path)
    assert exp.name == "demo"


def test_load_experiment_missing_file(tmp_path):
    with pytest.raises(ExperimentError, match="not found"):
        load_experiment(tmp_path / "missing.yaml")


def test_load_experiment_bad_yaml(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: [unclosed")
    with pytest.raises(ExperimentError, match="invalid YAML"):
        load_experiment(path)


def test_load_experiment_undecodable_file(tmp_path):
    path = tmp_path / "binary.yaml"
    path.write_bytes(b"\xff\xfe\x00not utf-8")
    with pytest.raises(ExperimentError, match="cannot read"):
        load_experiment(path)


@pytest.mark.parametrize("namespace", [None, "", "  ", 123])
def test_action_namespace_must_be_non_empty_string(namespace):
    target = {"namespace": namespace, "label_selector": "app=api"}
    data = {**VALID, "actions": [{"type": "pod_kill", "target": target}]}
    with pytest.raises(ExperimentError, match=r"actions\[0\]\.target\.namespace"):
        parse_experiment(data)
