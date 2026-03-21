"""Playwright e2e test configuration."""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks test as slow (e2e)")


@pytest.fixture(scope="session")
def base_url():
    return "http://localhost:8000"
