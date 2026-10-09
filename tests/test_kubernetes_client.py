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
