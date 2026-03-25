"""Playwright e2e test configuration."""
import os
import re

import pytest
import requests

# When SBE_AUTH_DISABLED=1 the server injects a fake admin — no login needed.
# When auth is enabled (default), we log in once per session via storage state.
_AUTH_DISABLED = os.getenv("SBE_AUTH_DISABLED", "").lower() in ("1", "true", "yes")
_BASE_URL = "http://localhost:8000"
_ADMIN_USER = os.getenv("SBE_ADMIN_USER", "admin")
_ADMIN_PASS = os.getenv("SBE_ADMIN_PASS", "testpassword123")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks test as slow (e2e)")


@pytest.fixture(scope="session")
def base_url():
    return _BASE_URL


@pytest.fixture(scope="session")
def auth_storage_state(browser):
    """Log in once per test session and return Playwright storage state.

    When SBE_AUTH_DISABLED=1 this returns None and no login is attempted.
    """
    if _AUTH_DISABLED:
        return None

    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{_BASE_URL}/login")
    page.fill("#username", _ADMIN_USER)
    page.fill("#password", _ADMIN_PASS)
    page.click("button[type='submit']")
    # Wait for redirect to the main app
    page.wait_for_url(f"{_BASE_URL}/", timeout=10_000)
    state = ctx.storage_state()
    ctx.close()
    return state


@pytest.fixture
def context(browser, auth_storage_state):
    """Provide an authenticated browser context for every test."""
    kwargs = {}
    if auth_storage_state:
        kwargs["storage_state"] = auth_storage_state
    ctx = browser.new_context(**kwargs)
    yield ctx
    ctx.close()


# ---------------------------------------------------------------------------
# Test-data cleanup — runs once at the end of the full test session
# ---------------------------------------------------------------------------

_TEST_PREFIXES = re.compile(
    r"^(E2E-|Dup-|DupSprint|LoadSprint|API-Sprint)",
    re.IGNORECASE,
)


def _cleanup_test_data() -> None:
    """Delete all tickets, sprints, and projects created by e2e tests."""
    session = requests.Session()
    base = _BASE_URL

    # --- tickets (search returns up to 500; loop until none remain) ---
    for prefix in ("E2E-",):
        while True:
            r = session.get(f"{base}/api/search", params={"q": prefix, "limit": 200})
            if not r.ok:
                break
            tickets = r.json() if isinstance(r.json(), list) else r.json().get("results", [])
            if not tickets:
                break
            for t in tickets:
                session.delete(f"{base}/api/tickets/{t['key']}")

    # --- sprints ---
    r = session.get(f"{base}/api/sprints")
    if r.ok:
        for s in r.json():
            if _TEST_PREFIXES.match(s.get("name", "")):
                session.delete(f"{base}/api/sprints/{s['id']}")

    # --- projects ---
    r = session.get(f"{base}/api/projects")
    if r.ok:
        for p in r.json():
            if _TEST_PREFIXES.match(p.get("name", "")):
                session.delete(f"{base}/api/projects/{p['id']}")


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data_after_session():
    """Auto-run test-data cleanup after the entire e2e session completes."""
    yield
    _cleanup_test_data()
