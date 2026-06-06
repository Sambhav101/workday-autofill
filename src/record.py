"""Record a submitted application to applications.yaml. Run this AFTER you click
Submit — it reads the confirmation page, captures the job + status, and appends a
tracked entry (de-duped by tenant+job id).

    ./venv/bin/python -m src.record
    ./venv/bin/python -m src.record --status "Under Consideration"
    ./venv/bin/python -m src.record --list
"""
from __future__ import annotations

import argparse
import datetime
import re
from pathlib import Path
from urllib.parse import urlparse, unquote

import yaml
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.table import Table

from . import browser

console = Console()
LOG_PATH = Path(__file__).resolve().parent.parent / "applications.yaml"
SIDECAR = Path(__file__).resolve().parent.parent / ".last_job.yaml"


def stash_job(job: dict, *, url: str = "", submitted_at: str = ""):
    """Called by apply.py at the Review step, while the URL still has job info.
    Saves everything needed to record later — the post-submit URL loses job context."""
    stashed = dict(job)
    if url:
        stashed["url"] = url.split("?")[0]
    if submitted_at:
        stashed["submitted_at"] = submitted_at
    SIDECAR.write_text(yaml.safe_dump(stashed))


def _sidecar() -> dict:
    if SIDECAR.exists():
        return yaml.safe_load(SIDECAR.read_text()) or {}
    return {}


def _load() -> list:
    if LOG_PATH.exists():
        return yaml.safe_load(LOG_PATH.read_text()) or []
    return []


def _save(entries: list):
    LOG_PATH.write_text(yaml.safe_dump(entries, sort_keys=False))


def parse_job(url: str, page=None) -> dict:
    host = urlparse(url).hostname or ""
    company = host.split(".")[0] if host else "unknown"
    title, job_id = "", ""
    m = re.search(r"/job/[^/]+/([^/]+?)(?:_([A-Za-z0-9._-]+))?(?:/|$)", url)
    if m:
        title = unquote(m.group(1)).replace("-", " ").strip()
        job_id = m.group(2) or ""
    # prefer the on-page heading for the title if available
    if page is not None:
        h = page.locator('h1, h2, [data-automation-id="pageHeader"]')
        if h.count():
            t = (h.first.inner_text() or "").strip()
            if t and t.lower() not in ("review",):
                title = t
    return {"company": company, "title": title, "job_id": job_id, "tenant": host}


def detect_status(page) -> str:
    """Best-effort read of the post-submit status from the page."""
    body = (page.locator("body").inner_text() or "").lower()
    if "you have already applied" in body or "submitted" in body or "thank you for applying" in body:
        return "Submitted"
    for s in ("Under Consideration", "Active", "In Review"):
        if s.lower() in body:
            return s
    return "Submitted"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", help="override the recorded status")
    ap.add_argument("--title", help="override the job title")
    ap.add_argument("--job-id", dest="job_id", help="override the job id")
    ap.add_argument("--list", action="store_true", help="print the tracker and exit")
    args = ap.parse_args()

    entries = _load()
    if args.list:
        _print(entries)
        return

    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_workday_tab(b)
        if not page:
            console.print("[red]No Workday tab open.[/red]")
            return
        job = parse_job(page.url, page)
        side = _sidecar()
        # post-submit URL often lacks job info — fall back to the stashed context
        for k in ("title", "job_id", "company", "tenant"):
            if not job.get(k) and side.get(k):
                job[k] = side[k]
        if args.title:
            job["title"] = args.title
        if args.job_id:
            job["job_id"] = args.job_id
        status = args.status or detect_status(page)
        entry = {
            **job,
            "url": page.url.split("?")[0],
            "status": status,
            "submitted_at": datetime.date.today().isoformat(),
        }
        # de-dupe by tenant + job_id; update existing
        key = (entry["tenant"], entry["job_id"])
        entries = [e for e in entries if (e.get("tenant"), e.get("job_id")) != key]
        entries.append(entry)
        _save(entries)
        console.print(f"[green]Recorded:[/green] {entry['company'].title()} — "
                      f"{entry['title']} ({entry['job_id']}) → [bold]{status}[/bold] "
                      f"on {entry['submitted_at']}")
        console.print(f"[dim]{len(entries)} application(s) tracked in {LOG_PATH.name}[/dim]")
        b.close()


def _print(entries: list):
    if not entries:
        console.print("No applications tracked yet.")
        return
    t = Table(title="Tracked applications")
    for c in ("Date", "Company", "Title", "Job ID", "Status"):
        t.add_column(c)
    for e in entries:
        t.add_row(e.get("submitted_at", ""), e.get("company", "").title(),
                  e.get("title", ""), e.get("job_id", ""), e.get("status", ""))
    console.print(t)


if __name__ == "__main__":
    main()
