"""Tests for CoreV1KubernetesClient config loading, with a stub package."""

import sys
import types

import pytest

from chaoskit.injectors.kubernetes import CoreV1KubernetesClient, KubernetesError


class ConfigException(Exception):
    pass


class ApiException(Exception):
    pass


class MaxRetryError(Exception):
    pass


@pytest.fixture
def stub_kubernetes(monkeypatch):
    """Install a minimal fake 'kubernetes' package with no usable config."""

    def load_kube_config():
        raise ConfigException("Invalid kube-config file. No configuration found.")

    def load_incluster_config():
        raise ConfigException("Service host/port is not set.")

    modules = {
        "kubernetes": types.ModuleType("kubernetes"),
        "kubernetes.client": types.ModuleType("kubernetes.client"),
        "kubernetes.client.exceptions": types.ModuleType(
            "kubernetes.client.exceptions"
        ),
        "kubernetes.config": types.ModuleType("kubernetes.config"),
        "kubernetes.config.config_exception": types.ModuleType(
            "kubernetes.config.config_exception"
        ),
        "urllib3": types.ModuleType("urllib3"),
        "urllib3.exceptions": types.ModuleType("urllib3.exceptions"),
    }
    modules["kubernetes"].client = modules["kubernetes.client"]
    modules["kubernetes"].config = modules["kubernetes.config"]
    modules["kubernetes.config"].load_kube_config = load_kube_config
    modules["kubernetes.config"].load_incluster_config = load_incluster_config
    modules["kubernetes.client.exceptions"].ApiException = ApiException
    modules["kubernetes.config.config_exception"].ConfigException = ConfigException
    modules["urllib3.exceptions"].MaxRetryError = MaxRetryError
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_config_error_reports_kubeconfig_problem(stub_kubernetes):
    # Outside a cluster the in-cluster error alone is misleading; the
    # kubeconfig failure is the one the user needs to see.
    with pytest.raises(KubernetesError) as excinfo:
        CoreV1KubernetesClient()
    message = str(excinfo.value)
    assert "kubeconfig: Invalid kube-config file" in message
    assert "in-cluster: Service host/port is not set" in message


class FakeExecStream:
    """Stands in for kubernetes.stream.ws_client.WSClient after the exec."""

    def __init__(self, returncode, output=""):
        self.returncode = returncode
        self._output = output
        self.closed = False

    def run_forever(self, timeout=None):
        pass

    def read_all(self):
        return self._output

    def close(self):
        self.closed = True


@pytest.fixture
def connected_client(stub_kubernetes, monkeypatch):
    """A CoreV1KubernetesClient whose config loads and whose exec is faked."""
    exec_ = types.SimpleNamespace(calls=[], response=None)

    class CoreV1Api:
        def connect_get_namespaced_pod_exec(self, *args, **kwargs):
            raise AssertionError("must be called through kubernetes.stream.stream")

    def stream(fn, **kwargs):
        exec_.calls.append(kwargs)
        return exec_.response

    stream_module = types.ModuleType("kubernetes.stream")
    stream_module.stream = stream
    monkeypatch.setitem(sys.modules, "kubernetes.stream", stream_module)
    monkeypatch.setattr(
        sys.modules["kubernetes.config"], "load_kube_config", lambda: None, raising=False
    )
    monkeypatch.setattr(sys.modules["kubernetes.client"], "CoreV1Api", CoreV1Api, raising=False)
    client = CoreV1KubernetesClient()
    return client, exec_


def test_exec_in_pod_raises_when_command_fails(connected_client):
    # Seen on a real cluster: exec'ing stress-ng in an image without it
    # returned the runtime's error text with status 127, and chaos-kit
    # reported the stress as injected.
    client, exec_ = connected_client
    exec_.response = FakeExecStream(
        127, 'exec: "stress-ng": executable file not found in $PATH\n'
    )
    with pytest.raises(KubernetesError) as excinfo:
        client.exec_in_pod("default", "api-1", ["stress-ng", "--cpu", "1"])
    message = str(excinfo.value)
    assert "default/api-1" in message
    assert "exited with status 127" in message
    assert "executable file not found" in message
    assert exec_.calls[0]["_preload_content"] is False
    assert exec_.response.closed


def test_exec_in_pod_succeeds_on_zero_exit(connected_client):
    client, exec_ = connected_client
    exec_.response = FakeExecStream(0, "ok\n")
    client.exec_in_pod("default", "api-1", ["sh", "-c", "echo ok"])
    assert exec_.response.closed


def test_exec_in_pod_raises_without_exit_status(connected_client):
    client, exec_ = connected_client
    exec_.response = FakeExecStream(None)
    with pytest.raises(KubernetesError, match="did not report an exit status"):
        client.exec_in_pod("default", "api-1", ["true"])
