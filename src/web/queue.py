"""Job queue: a simple YAML-backed list of URLs to process."""
from __future__ import annotations

import datetime
from pathlib import Path
from threading import Lock

import yaml

QUEUE_PATH = Path(__file__).resolve().parent.parent.parent / "queue.yaml"
_lock = Lock()


def _load() -> list[dict]:
    with _lock:
        if QUEUE_PATH.exists():
            return yaml.safe_load(QUEUE_PATH.read_text()) or []
        return []


def _save(entries: list[dict]):
    with _lock:
        QUEUE_PATH.write_text(yaml.safe_dump(entries, sort_keys=False))


def add_urls(urls: list[str]) -> int:
    entries = _load()
    existing = {e["url"] for e in entries}
    added = 0
    for url in urls:
        url = url.strip()
        if not url or url in existing:
            continue
        entries.append({
            "url": url,
            "status": "queued",
            "added_at": datetime.datetime.now().isoformat(timespec="seconds"),
        })
        existing.add(url)
        added += 1
    _save(entries)
    return added


def get_all() -> list[dict]:
    return _load()


def get_queued() -> list[dict]:
    return [e for e in _load() if e["status"] == "queued"]


def update_status(url: str, status: str, reason: str = ""):
    entries = _load()
    for e in entries:
        if e["url"] == url:
            e["status"] = status
            if reason:
                e["reason"] = reason
            e["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            break
    _save(entries)


def remove_completed():
    entries = _load()
    entries = [e for e in entries if e["status"] not in ("submitted", "skipped")]
    _save(entries)


def clear_all():
    _save([])
