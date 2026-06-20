"""ATS routing for the autofill pipeline. Spike-level: a host check only."""
from __future__ import annotations

from urllib.parse import urlparse


def detect_ats(url: str) -> str:
    """Identify the ATS provider from a job URL. Returns 'workday', 'lever', 'ashby', or 'unknown'."""
    host = (urlparse(url).hostname or "").lower()
    if "myworkdayjobs.com" in host:
        return "workday"
    if "jobs.lever.co" in host:
        return "lever"
    if "jobs.ashbyhq.com" in host:
        return "ashby"
    return "unknown"


from .base import ApplyResult, ApplyStatus, ATSDriver
from .workday import WorkdayDriver
from .lever import LeverDriver
from .ashby import AshbyDriver

_REGISTRY: dict[str, ATSDriver] = {
    "workday": WorkdayDriver(),
    "lever": LeverDriver(),
    "ashby": AshbyDriver(),
}


def driver_for(url: str) -> ATSDriver | None:
    """Return the driver for a job URL, or None if no ATS matches."""
    return _REGISTRY.get(detect_ats(url))


def dispatch(page, url: str, *, auto_submit: bool) -> ApplyResult:
    """Route one job URL to its driver. Unknown host → ERROR result (no raise)."""
    driver = driver_for(url)
    if driver is None:
        return ApplyResult(ApplyStatus.ERROR, f"No driver for URL: {url}", {"url": url})
    return driver.apply(page, url, auto_submit=auto_submit)


_KEEP_OPEN = {ApplyStatus.CAPTCHA, ApplyStatus.REVIEW, ApplyStatus.BLOCKED}


def keeps_tab_open(status) -> bool:
    """True if a job's outcome needs the human, so its tab should stay open for review."""
    return ApplyStatus(status) in _KEEP_OPEN


def run_batch(urls: list[str], *, auto_submit: bool = True) -> list[ApplyResult]:
    """Apply to multiple jobs across any supported ATS. Errors are logged, not raised."""
    from pathlib import Path
    import yaml
    from playwright.sync_api import sync_playwright
    from rich.console import Console
    from rich.table import Table
    from .. import browser

    console = Console()
    report_path = Path(__file__).resolve().parent.parent.parent / "report.yaml"
    results: list[ApplyResult] = []

    with sync_playwright() as pw:
        b = browser.connect(pw)
        ctx = b.contexts[0] if b.contexts else None
        if ctx is None:
            console.print("[red]No browser context available.[/red]")
            return results

        needs_you = 0
        for i, url in enumerate(urls, 1):
            console.rule(f"[bold]Job {i}/{len(urls)}[/bold]")
            page = ctx.new_page()
            try:
                result = dispatch(page, url, auto_submit=auto_submit)
            except Exception as e:  # noqa: BLE001
                result = ApplyResult(ApplyStatus.ERROR, str(e), {"url": url})
            results.append(result)
            job = result.job
            line = f"{job.get('title', '?')} @ {job.get('tenant', '?')} — {result.status.value}"
            color = {"submitted": "green", "review": "cyan", "skipped": "dim",
                     "captcha": "magenta", "blocked": "yellow", "error": "red"}.get(
                         result.status.value, "white")
            console.print(f"[{color}]{line}: {result.reason}[/{color}]")
            report_path.write_text(yaml.safe_dump(
                [r.to_dict() for r in results], default_flow_style=False, sort_keys=False))
            if keeps_tab_open(result.status):
                needs_you += 1
            else:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass

        b.close()

    from .notify import notify
    notify("Autofill finished",
           f"{needs_you} job(s) need you — solve captcha / review & submit"
           if needs_you else "All jobs processed.")

    console.rule("[bold]Batch Summary[/bold]")
    table = Table()
    for col in ("Job", "Company", "Status", "Reason"):
        table.add_column(col)
    for r in results:
        color = {"submitted": "green", "review": "cyan", "skipped": "dim",
                 "captcha": "magenta", "blocked": "yellow", "error": "red"}.get(
                     r.status.value, "white")
        table.add_row(r.job.get("title", "?")[:40], r.job.get("tenant", "?"),
                      f"[{color}]{r.status.value}[/{color}]", r.reason[:60])
    console.print(table)
    console.print(f"\nFull report saved to [bold]{report_path}[/bold]")
    return results
