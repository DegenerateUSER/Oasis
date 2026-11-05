"""No expensive provider downloads unless explicitly requested."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--run-provider-tests", action="store_true", default=False,
                     help="opt in to provider downloads/network integration tests")


def pytest_configure(config):
    config.addinivalue_line("markers", "provider_integration: requires downloaded providers/network")
    config.addinivalue_line("markers", "engine_smoke: small provider-free real Terraform/OpenTofu check")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-provider-tests"):
        skip = pytest.mark.skip(reason="provider/network tests are opt-in: --run-provider-tests")
        for item in items:
            if "provider_integration" in item.keywords:
                item.add_marker(skip)
