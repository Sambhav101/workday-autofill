"""Smoke tests. The CDP test is skipped unless a real Chrome is running with
remote debugging (so CI / normal runs stay green without a browser)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import browser  # noqa: E402


def test_imports():
    """The browser module loads and exposes its API."""
    assert hasattr(browser, "connect")
    assert hasattr(browser, "find_workday_tab")
    assert browser.CDP_PORT == 9222


@pytest.mark.skipif(not browser.cdp_available(), reason="no Chrome on CDP port 9222")
def test_cdp_connect():
    """If a debuggable Chrome is up, we can attach and list contexts."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = browser.connect(pw)
        assert b.contexts is not None
        b.close()
