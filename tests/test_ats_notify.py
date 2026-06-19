# tests/test_ats_notify.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.ats.notify as notify_mod
from src.ats.notify import notify


def test_notify_returns_none():
    assert notify("Title", "Message") is None


def test_notify_never_raises_when_backend_fails(monkeypatch):
    def boom(*a, **k):
        raise OSError("backend unavailable")
    monkeypatch.setattr(notify_mod.subprocess, "run", boom)
    # must swallow the error on every platform path that shells out
    notify("Title", "Message")


def test_notify_handles_quotes_in_text():
    # double quotes in the message must not break the osascript string build
    notify('a "quoted" title', 'msg with "quotes"')
