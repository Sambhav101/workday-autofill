"""Background runner: processes the job queue one URL at a time."""
from __future__ import annotations

import json
import threading
import time
from typing import Callable

from playwright.sync_api import sync_playwright

from .. import browser
from ..record import _load as load_applications
from . import queue as Q

_running = False
_stop_flag = False
_listeners: list[Callable] = []


def is_running() -> bool:
    return _running


def stop():
    global _stop_flag
    _stop_flag = True


def add_listener(fn: Callable):
    _listeners.append(fn)


def remove_listener(fn: Callable):
    if fn in _listeners:
        _listeners.remove(fn)


def _emit(event: str, data: dict):
    msg = json.dumps({"event": event, **data})
    for fn in _listeners[:]:
        try:
            fn(msg)
        except Exception:
            pass


def run_queue(backend: str = "direct", auto_submit: bool = True):
    """Process all queued jobs. Runs in a thread.
    backend='direct' uses the pipeline directly (no LLM agent needed).
    backend='claude' or 'ollama' would use the agent (future)."""
    global _running, _stop_flag
    if _running:
        return
    _running = True
    _stop_flag = False

    def _worker():
        global _running, _stop_flag
        try:
            pw = sync_playwright().start()
            b = browser.connect(pw)
            page = browser.find_any_tab(b)
            if not page:
                _emit("error", {"message": "No Chrome tab available"})
                return

            while not _stop_flag:
                queued = Q.get_queued()
                if not queued:
                    _emit("done", {"message": "All jobs processed"})
                    break

                job = queued[0]
                url = job["url"]
                Q.update_status(url, "running")
                _emit("status", {"url": url, "status": "running"})

                try:
                    from ..ats import dispatch
                    result = dispatch(page, url, auto_submit=auto_submit).to_dict()
                    status = result.get("status", "error")
                    reason = result.get("reason", "")
                    title = result.get("title", "")
                    Q.update_status(url, status, reason)
                    _emit("result", {
                        "url": url, "status": status, "reason": reason,
                        "title": title, "tenant": result.get("tenant", ""),
                    })
                except Exception as e:
                    Q.update_status(url, "error", str(e))
                    _emit("result", {"url": url, "status": "error", "reason": str(e)[:200]})

            b.close()
            pw.stop()
        except Exception as e:
            _emit("error", {"message": str(e)[:200]})
        finally:
            _running = False
            _emit("stopped", {})

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
