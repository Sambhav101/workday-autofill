"""Connect to the user's real Chrome over the DevTools Protocol (CDP).

Why CDP instead of a fresh Playwright browser: we want the user's existing
logins/cookies and a human-looking session, so we attach to a Chrome the user
launched themselves with --remote-debugging-port. See README for launch steps.
"""
from __future__ import annotations

import urllib.request
import urllib.error
from playwright.sync_api import sync_playwright, Browser, Page

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"


def cdp_available(port: int = CDP_PORT) -> bool:
    """True if a Chrome is listening for CDP on the given port."""
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=2):
            return True
    except (urllib.error.URLError, OSError):
        return False


def connect(pw) -> Browser:
    """Attach to the already-running real Chrome. Caller owns the playwright ctx."""
    if not cdp_available():
        raise RuntimeError(
            f"No Chrome found on CDP port {CDP_PORT}. "
            "Launch it first (see README): quit Chrome, then run scripts/launch_chrome.sh"
        )
    return pw.chromium.connect_over_cdp(CDP_URL)


def find_workday_tab(browser: Browser) -> Page | None:
    """Return the open tab pointing at a Workday tenant, if any."""
    for ctx in browser.contexts:
        for page in ctx.pages:
            if "myworkdayjobs.com" in (page.url or ""):
                return page
    return None


def find_any_tab(browser: Browser) -> Page | None:
    """Return any open tab (prefer Workday, fall back to any page)."""
    wd = find_workday_tab(browser)
    if wd:
        return wd
    for ctx in browser.contexts:
        for page in ctx.pages:
            if page.url and "chrome://" not in page.url:
                return page
    # last resort: even chrome:// tabs
    for ctx in browser.contexts:
        if ctx.pages:
            return ctx.pages[0]
    return None
