# tests/test_ats_notify.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import src.ats.notify as notify_mod
from src.ats.notify import notify


@pytest.fixture(autouse=True)
def _silence_real_notifications(monkeypatch):
    """Never fire a real OS notification during tests (no Glass toast, no beep).
    Stub the shell-out and the Windows beep so the suite stays silent everywhere."""
    calls = []
    monkeypatch.setattr(notify_mod.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    if sys.platform == "win32":
        import winsound
        monkeypatch.setattr(winsound, "MessageBeep", lambda *a, **k: None)
    return calls


def test_notify_returns_none():
    assert notify("Title", "Message") is None


def test_notify_never_raises_when_backend_fails(monkeypatch):
    def boom(*a, **k):
        raise OSError("backend unavailable")
    monkeypatch.setattr(notify_mod.subprocess, "run", boom)
    # must swallow the error on every platform path that shells out
    notify("Title", "Message")


def test_notify_escapes_quotes_for_osascript(_silence_real_notifications, monkeypatch):
    # Force the macOS path so the escaping is exercised regardless of the test host.
    monkeypatch.setattr(sys, "platform", "darwin")
    notify('title', 'msg with "quotes"')
    assert _silence_real_notifications, "darwin path should shell out to osascript"
    args, _ = _silence_real_notifications[-1]
    script = args[0][-1]  # the osascript -e payload
    assert 'msg with "quotes"' not in script   # raw double-quotes would break the script
    assert "msg with 'quotes'" in script       # …they're escaped to single quotes
