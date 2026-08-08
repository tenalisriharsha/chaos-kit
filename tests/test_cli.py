"""Tests for the chaoskit CLI."""

import textwrap

import pytest

from chaoskit.cli import main

VALID_YAML = textwrap.dedent(
    """\
    name: cli-demo
    description: demo
    steady_state:
      - name: errors
        query: rate(errors[5m])
        operator: lt
        threshold: 0.01
    actions:
      - type: pod_kill
        target:
          label_selector: app=api
    """
)


@pytest.fixture
def experiment_file(tmp_path):
    path = tmp_path / "exp.yaml"
    path.write_text(VALID_YAML)
    return path


def test_validate_ok(experiment_file, capsys):
    assert main(["validate", str(experiment_file)]) == 0
    out = capsys.readouterr().out
    assert "cli-demo" in out
    assert "OK" in out


def test_validate_invalid(tmp_path, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text("actions: []")
    assert main(["validate", str(path)]) == 2
    assert "INVALID" in capsys.readouterr().err


def test_validate_missing_file(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "nope.yaml")]) == 2
    assert "not found" in capsys.readouterr().err


def test_check_pass(experiment_file, prometheus, capsys):
    prometheus.respond_value(0.001)
    rc = main(["check", str(experiment_file), "--prometheus", prometheus.url])
    assert rc == 0
    out = capsys.readouterr().out
    assert "PASS errors" in out
    assert "Steady state: OK" in out
    assert prometheus.queries == ["rate(errors[5m])"]


def test_check_fail(experiment_file, prometheus, capsys):
    prometheus.respond_value(0.5)
    rc = main(["check", str(experiment_file), "--prometheus", prometheus.url])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL errors" in out
    assert "VIOLATED" in out


def test_check_unreachable(experiment_file, capsys):
    rc = main(["check", str(experiment_file), "--prometheus", "http://127.0.0.1:1"])
    assert rc == 2
    assert "ERROR" in capsys.readouterr().err
