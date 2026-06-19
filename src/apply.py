"""End-to-end runner: walk every page of a Workday application, fill each from
profile.yaml, click Save & Continue, and STOP at the Review page (Submit button).
Pass --submit to also click Submit and record the application automatically.

    ./venv/bin/python -m src.apply                          # fill current tab
    ./venv/bin/python -m src.apply --submit URL             # single job
    ./venv/bin/python -m src.apply --submit URL1 URL2 ...   # batch mode
"""
from __future__ import annotations

import argparse
import datetime
from playwright.sync_api import sync_playwright, Page
from rich.console import Console

from . import browser
from .browser import find_any_tab
from .discover import discover_page, discover_fields
from .fill import fill_my_information
from .experience import fill_experience
from .questions import fill_questions
from .disclosures import fill_disclosures
from .selfid import fill_selfid
from .signup import create_or_sign_in, sign_in, _on_signin_page, _tenant
from .profile import load_profile
from .widgets import _poll

console = Console()
NEXT = '[data-automation-id="pageFooterNextButton"]'
_job_title: str = ""

# Selectors that indicate the page has meaningful content loaded
_PAGE_CONTENT_MARKERS = (
    '[data-automation-id^="formField-"]',
    '[data-automation-id="signInSubmitButton"]',
    '[data-automation-id="createAccountSubmitButton"]',
    '[data-automation-id="createAccountLink"]',
    '[data-automation-id="SignInWithEmailButton"]',
    '[data-automation-id="email"]',
    '[data-automation-id="pageFooterNextButton"]',
    'button:has-text("Submit")',
)


def _wait_for_page_content(page: Page, *, timeout_ms: int = 15000):
    """Wait for the page to have actual content — form fields, sign-in, etc.
    If nothing appears, refresh once and wait again."""
    found = _poll(
        lambda: any(page.locator(sel).count() > 0 for sel in _PAGE_CONTENT_MARKERS),
        timeout_ms=timeout_ms, interval_ms=500,
    )
    if not found:
        console.print("[yellow]  Page appears empty — refreshing...[/yellow]")
        page.reload()
        page.wait_for_timeout(2000)
        _poll(
            lambda: any(page.locator(sel).count() > 0 for sel in _PAGE_CONTENT_MARKERS),
            timeout_ms=timeout_ms, interval_ms=500,
        )
    page.wait_for_timeout(1000)


# ── pre-application flow ────────────────────────────────────────────────────

def _handle_apply_button(page: Page):
    """If on a job posting page, click Apply and handle the method popup."""
    tree = discover_page(page)
    console.print(f"  [dim]{tree['field_count']} fields, {tree['unfilled_count']} unfilled[/dim]")

    apply_btn = page.locator('[data-automation-id="adventureButton"]')
    continue_link = page.locator('a:has-text("Continue Application")')
    if continue_link.count():
        console.print("[cyan]Clicking Continue Application...[/cyan]")
        continue_link.first.click()
        _wait_for_page_content(page)
        return
    if not apply_btn.count():
        return
    console.print("[cyan]Clicking Apply...[/cyan]")
    apply_btn.first.click()
    page.wait_for_timeout(2000)

    tree = discover_page(page)
    console.print(f"  [dim]After Apply click: {tree['field_count']} fields[/dim]")

    # Popup: "Autofill with Resume" / "Apply Manually" / "Use My Last Application"
    manual = page.locator('[data-automation-id="applyManually"]')
    if manual.count():
        console.print("[cyan]Apply popup detected — clicking Apply Manually.[/cyan]")
        manual.first.click()
        _poll(
            lambda: page.locator('[data-automation-id="applyManually"]').count() == 0,
            timeout_ms=8000, interval_ms=300,
        )
        _wait_for_page_content(page)
        tree = discover_page(page)
        console.print(f"  [dim]After Apply Manually: {tree['field_count']} fields, "
                      f"{tree['unfilled_count']} unfilled[/dim]")


def _handle_signup(page: Page):
    """If on the sign-in / create-account page, handle it."""
    tree = discover_page(page)
    console.print(f"  [dim]{tree['field_count']} fields, {tree['unfilled_count']} unfilled[/dim]")

    signin_markers = [
        '[data-automation-id="signInSubmitButton"]',
        '[data-automation-id="createAccountSubmitButton"]',
        '[data-automation-id="createAccountLink"]',
        '[data-automation-id="SignInWithEmailButton"]',
    ]
    if not any(page.locator(sel).count() > 0 for sel in signin_markers):
        return
    console.print("[cyan]Sign-in / account creation page detected.[/cyan]")
    profile = load_profile()
    result = create_or_sign_in(page, profile, auto_email=False)
    console.print(f"[cyan]Signup result: {result}[/cyan]")

    # If still on sign-in page (e.g. after verify-then-signin), retry sign-in
    page.wait_for_timeout(2000)
    if _on_signin_page(page):
        console.print("[yellow]Still on sign-in page — retrying sign in...[/yellow]")
        creds = profile.get("credentials", {})
        result = sign_in(page, creds, _tenant(page.url), auto_email=False)
        console.print(f"[cyan]Retry sign-in result: {result}[/cyan]")

    _wait_for_page_content(page)
    tree = discover_page(page)
    console.print(f"  [dim]After signup: {tree['field_count']} fields, "
                  f"{tree['unfilled_count']} unfilled[/dim]")


# ── page detection ───────────────────────────────────────────────────────────
# Each detector is (name, check_fn). Ordered from most-specific to least.
# A check returns True only if a *distinguishing* marker for that page is present.

def _has(page: Page, sel: str) -> bool:
    return page.locator(sel).count() > 0


PAGE_CHECKS = [
    ("assessment", lambda p: (
        p.locator('[data-automation-id="errorMessage"]:has-text("assessment")').count() > 0
        or p.locator('text="complete the assessment"').count() > 0
    )),

    ("review", lambda p: p.locator('button[data-automation-id="bottom-navigation-next-button"]'
                                    ':has-text("Submit")').count() > 0
                         or (p.locator('button:has-text("Submit")').count() > 0
                             and not _has(p, '[data-automation-id="formField-legalName--firstName"]'))),

    ("my_information", lambda p: _has(p, '[data-automation-id="formField-legalName--firstName"]')),

    ("my_experience", lambda p: (
        _has(p, '[data-automation-id="formField-jobTitle"]')
        or _has(p, '[data-automation-id="formField-schoolName"]')
        or _has(p, '[data-automation-id="formField-school"]')
        or _has(p, 'input[type="file"]')
    )),

    ("self_id", lambda p: (
        _has(p, '[data-automation-id="formField-disabilityForm"]')
        or _has(p, '[data-automation-id="disabilityStatus-CheckboxGroup"]')
        or _has(p, 'label:has-text("PLEASE READ THIS LANGUAGE")')
        or _has(p, 'label:has-text("disability")')
    )),

    ("disclosures", lambda p: (
        _has(p, '[data-automation-id="formField-gender"]')
        or _has(p, '[data-automation-id="formField-veteranStatus"]')
        or _has(p, '[data-automation-id="formField-ethnicity"]')
    )),

    ("questions", lambda p: (
        p.locator('button[aria-haspopup="listbox"]').count() >= 2
        or _has(p, '[data-automation-id="questionSet"]')
    )),
]


def detect(page: Page) -> str:
    """Wait for the page to settle, then identify by marker elements."""
    # Wait for any loading overlay / spinner to disappear
    _poll(
        lambda: not page.locator('[data-automation-id="loadingSpinner"], '
                                  '.wd-LoadingIndicator, '
                                  '[aria-label="Loading"]').count(),
        timeout_ms=8000,
        interval_ms=200,
    )
    # Brief settle for DOM to finish rendering
    page.wait_for_timeout(400)

    for name, check in PAGE_CHECKS:
        try:
            if check(page):
                return name
        except Exception:  # noqa: BLE001
            continue
    return "unknown"


# ── page fillers ─────────────────────────────────────────────────────────────

FILLERS = {
    "my_information": lambda p: fill_my_information(p),
    "my_experience": lambda p: fill_experience(p),
    "questions": lambda p: (fill_questions(p, job_title=_job_title) or []),
    "disclosures": lambda p: fill_disclosures(p),
    "self_id": lambda p: fill_selfid(p),
}


def _wait_page_ready(page: Page, *, timeout_ms=8000):
    """Wait for the page to be interactive (no spinners, Next button present)."""
    _poll(
        lambda: not page.locator('[data-automation-id="loadingSpinner"], '
                                  '.wd-LoadingIndicator').count(),
        timeout_ms=timeout_ms,
        interval_ms=200,
    )


def _check_required_fields(page: Page) -> list[str]:
    """Return list of required-but-empty field labels. Empty list = all good."""
    fields = discover_fields(page)
    missing = []
    placeholders = {"select one", "—", "--", ""}
    for f in fields:
        if not f.get("visible") or not f.get("required"):
            continue
        if f["widget"] == "checkbox":
            wrap = page.locator(f'[data-automation-id="{f["aid"]}"]')
            if wrap.count():
                cbs = wrap.first.locator('input[type="checkbox"]')
                if any(cbs.nth(i).is_checked() for i in range(cbs.count())):
                    continue
        val = (f.get("value") or "").strip().lower()
        if val in placeholders:
            label = f.get("label") or f.get("aid", "unknown")
            missing.append(label)
    return missing


def _click_next(page: Page) -> bool:
    """Click the Next/Save & Continue button and wait for navigation."""
    nxt = page.locator(NEXT)
    if not nxt.count():
        return False
    # Capture something to detect page change
    old_kind = detect(page)
    nxt.first.scroll_into_view_if_needed()
    nxt.first.click()
    # Wait for either: page changes, spinner appears then disappears, or errors show
    _poll(
        lambda: (page.locator('[data-automation-id="loadingSpinner"], '
                               '.wd-LoadingIndicator').count() > 0
                 or page.locator('[data-automation-id="errorMessage"]').count() > 0),
        timeout_ms=3000,
        interval_ms=150,
    )
    # Now wait for loading to finish
    _wait_page_ready(page, timeout_ms=10000)
    page.wait_for_timeout(500)
    return True


def _submit_and_record(page: Page, job: dict):
    """Click Submit, wait for confirmation, and record to applications.yaml."""
    from .record import stash_job, _load, _save

    pre_submit_url = page.url.split("?")[0]
    stash_job(job, url=pre_submit_url)

    submit = page.locator('[data-automation-id="pageFooterNextButton"]')
    if not submit.count():
        console.print("[red]No Submit button found.[/red]")
        return
    submit.first.scroll_into_view_if_needed()
    submit.first.click()
    page.wait_for_timeout(5000)

    entry = {
        **job,
        "url": pre_submit_url,
        "status": "Submitted",
        "submitted_at": datetime.date.today().isoformat(),
    }
    entries = _load()
    key = (entry["tenant"], entry["job_id"])
    if key[1]:
        entries = [e for e in entries if (e.get("tenant"), e.get("job_id")) != key]
    entries.append(entry)
    _save(entries)
    console.print(f"[green]Submitted & recorded:[/green] {entry['company'].title()} — "
                  f"{entry['title']} ({entry['job_id']})")


def _run_one(page, *, auto_submit: bool = False, max_pages: int = 10) -> dict:
    """Fill one job application on the current page. Returns a result dict:
        {"status": "submitted"|"review"|"blocked"|"error", "reason": "...", **job_meta}
    """
    global _job_title

    from .record import parse_job, stash_job, _load as _load_applications
    original_url = page.url
    _job_meta = parse_job(original_url, page)
    try:
        heading = page.locator('[data-automation-id="jobPostingHeader"]').first
        if heading.count():
            _job_title = heading.inner_text().strip()
            _job_meta["title"] = _job_title
        else:
            _job_title = page.title().split("|")[0].strip()
            if _job_title:
                _job_meta["title"] = _job_title
    except Exception:  # noqa: BLE001
        _job_title = _job_meta.get("title", "")
    _job_meta["url"] = original_url.split("?")[0]
    console.print(f"[bold]{_job_meta['title']}[/bold] @ {_job_meta['tenant']}"
                  f" (id: {_job_meta.get('job_id', '?')})")

    def _result(status: str, reason: str) -> dict:
        return {"status": status, "reason": reason, **_job_meta}

    # ── duplicate check: skip if already submitted ──
    if _job_meta.get("job_id"):
        prior = _load_applications()
        for entry in prior:
            if (entry.get("tenant") == _job_meta.get("tenant")
                    and entry.get("job_id") == _job_meta["job_id"]
                    and entry.get("status") == "Submitted"):
                msg = f"Already applied on {entry.get('submitted_at', '?')}"
                console.print(f"[yellow]{msg} — skipping.[/yellow]")
                return _result("skipped", msg)

    # ── pre-application: Apply button → popup → signup ──
    _handle_apply_button(page)
    _handle_signup(page)

    seen = []
    for step in range(max_pages):
        _wait_for_page_content(page)
        kind = detect(page)
        if kind == "assessment":
            msg = "Assessment page — external test required"
            console.print(f"\n[bold yellow]{msg}[/bold yellow]")
            return _result("blocked", msg)
        if kind == "review":
            stash_job(_job_meta, url=_job_meta["url"])
            console.print("\n[bold green]Reached Review page — Submit button present.[/bold green]")
            if auto_submit:
                _submit_and_record(page, _job_meta)
                return _result("submitted", "Submitted and recorded")
            else:
                console.print("Stopping. Review in Chrome and click Submit yourself, "
                              "then run [bold]python -m src.record[/bold].")
                return _result("review", "Stopped at Review page")
        if kind == "unknown":
            console.print(f"[yellow]Page {step + 1}: unknown — trying all fillers.[/yellow]")
            tree = discover_page(page)
            console.print(f"  [dim]{tree['field_count']} fields, "
                          f"{tree['unfilled_count']} unfilled[/dim]")
            for filler_name, filler_fn in FILLERS.items():
                try:
                    filler_fn(page)
                except Exception:  # noqa: BLE001
                    pass
            seen.append("unknown")
            missing = _check_required_fields(page)
            if missing:
                console.print(f"[yellow]  Required fields still empty: {missing}[/yellow]")
                msg = f"Required fields unfilled on unknown page: {missing}"
                return _result("blocked", msg)
            if not _click_next(page):
                msg = "No Next button on unknown page"
                console.print(f"[yellow]{msg} — stopping.[/yellow]")
                return _result("blocked", msg)
            errs = page.locator('[data-automation-id="errorMessage"]')
            if errs.count():
                err_texts = [errs.nth(i).inner_text()[:120] for i in range(min(errs.count(), 8))]
                msg = f"Validation errors on unknown page: {'; '.join(err_texts)}"
                console.print(f"[red]{msg}[/red]")
                return _result("blocked", msg)
            continue
        console.print(f"[cyan]Page {step + 1}:[/cyan] {kind}")
        tree = discover_page(page)
        console.print(f"  [dim]{tree['field_count']} fields, "
                      f"{tree['unfilled_count']} unfilled[/dim]")
        if tree["page_info"].get("hasPopup"):
            console.print("[red]  Popup blocking page — handling...[/red]")
        FILLERS[kind](page)
        seen.append(kind)

        missing = _check_required_fields(page)
        if missing:
            console.print(f"[yellow]  Required fields still empty on '{kind}': {missing}[/yellow]")
            msg = f"Required fields unfilled on '{kind}': {missing}"
            return _result("blocked", msg)

        if not _click_next(page):
            msg = f"No Next button after filling '{kind}'"
            console.print(f"[yellow]{msg} — stopping.[/yellow]")
            return _result("blocked", msg)

        errs = page.locator('[data-automation-id="errorMessage"]')
        if errs.count():
            err_texts = [errs.nth(i).inner_text()[:120] for i in range(min(errs.count(), 8))]
            msg = f"Validation errors on '{kind}': {'; '.join(err_texts)}"
            console.print(f"[red]{msg}[/red]")
            return _result("blocked", msg)

    msg = f"Hit page limit ({max_pages}). Filled: {seen}"
    console.print(f"[yellow]{msg}[/yellow]")
    return _result("blocked", msg)


# ── batch runner ────────────────────────────────────────────────────────────

def run_batch(urls: list[str], *, auto_submit: bool = True) -> list[dict]:
    """Apply to multiple jobs (any supported ATS). Delegates to the shared dispatcher."""
    from .ats import run_batch as ats_run_batch
    return [r.to_dict() for r in ats_run_batch(urls, auto_submit=auto_submit)]


def main(url: str | None = None, *, auto_submit: bool = False) -> dict:
    """Single-job entry point. With a URL, route via the ATS dispatcher; without one,
    fill the current Workday tab (unchanged behavior)."""
    if url:
        from .ats import dispatch
        with sync_playwright() as pw:
            b = browser.connect(pw)
            page = browser.find_any_tab(b)
            if not page:
                console.print("[red]No Chrome tab available.[/red]")
                return {"status": "error", "reason": "No Chrome tab available"}
            result = dispatch(page, url, auto_submit=auto_submit).to_dict()
            b.close()
            return result
    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_workday_tab(b)
        if not page:
            console.print("[red]No Chrome tab available.[/red]")
            return {"status": "error", "reason": "No Chrome tab available"}
        result = _run_one(page, auto_submit=auto_submit)
        b.close()
        return result


if __name__ == "__main__":
    import sys
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*", help="job URLs (batch mode if multiple)")
    ap.add_argument("--submit", action="store_true",
                    help="also click Submit and record (default: stop at Review)")
    args = ap.parse_args()
    if len(args.urls) > 1:
        run_batch(args.urls, auto_submit=args.submit)
    else:
        url = args.urls[0] if args.urls else None
        result = main(url=url, auto_submit=args.submit)
        if result and result["status"] in ("blocked", "error"):
            sys.exit(1)
