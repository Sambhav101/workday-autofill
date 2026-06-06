"""Fill the Workday "Voluntary Self-Identification of Disability" (CC-305) form:
name, today's date, and disability status from profile.yaml (user-set only).
Stops before submit.

    ./venv/bin/python -m src.selfid
"""
from __future__ import annotations

import datetime
from playwright.sync_api import sync_playwright, Page
from rich.console import Console

from . import browser, widgets
from .profile import load_profile

console = Console()


def _type_date(page: Page, value: datetime.date):
    """Today's signature date into the MM / DD / YYYY spinbuttons."""
    for aid, num in (("dateSectionMonth-input", value.month),
                     ("dateSectionDay-input", value.day),
                     ("dateSectionYear-input", value.year)):
        el = page.locator(f'[data-automation-id="{aid}"]').first
        if el.count():
            el.evaluate("e=>e.scrollIntoView({block:'center'})")
            el.evaluate("e=>e.focus()")
            page.keyboard.type(str(num), delay=60)
            page.wait_for_timeout(150)


def fill_selfid(page: Page):
    """Fill the CC-305 self-identification page on a shared page. Returns rows."""
    p = load_profile()
    name = f"{p['identity']['first_name']} {p['identity']['last_name']}"
    status = str(p.get("sensitive", {}).get("disability_status", "")).strip().lower()
    if status in ("no", "false", "n"):
        want = "No, I do not have a disability"
    elif status in ("yes", "true", "y"):
        want = "Yes, I have a disability"
    else:
        want = "I do not want to answer"

    results = [("Name", *widgets.fill_text(page, "formField-name", name))]
    _type_date(page, datetime.date.today())
    results.append(("Date", True, "today"))
    # Try scoped to the disability field first, then fall back to whole page
    disability_wrap = page.locator(
        '[data-automation-id="formField-disabilityStatus"], '
        '[data-automation-id="disabilityStatus-CheckboxGroup"]'
    )
    search_root = disability_wrap.first if disability_wrap.count() else page
    lbl = search_root.locator('label', has_text=want)
    if not lbl.count():
        lbl = page.locator('label', has_text=want)
    if lbl.count():
        try:
            fid = lbl.first.get_attribute("for")
            box = page.locator(f'[id="{fid}"]') if fid else page.locator("x:nope")
            if box.count():
                box.first.scroll_into_view_if_needed()
                if not box.first.is_checked():
                    box.first.check()
            else:
                lbl.first.scroll_into_view_if_needed()
                lbl.first.click()
            results.append((f"Disability: {want[:25]}", True, "checked"))
        except Exception as e:  # noqa: BLE001
            results.append(("Disability", False, f"error: {e}"))
    else:
        results.append(("Disability", False, f"no option ~ {want!r}"))
    return results


def main():
    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_workday_tab(b)
        if not page:
            console.print("[red]No Workday tab open.[/red]")
            return
        for f, ok, note in fill_selfid(page):
            mark = "[green]ok[/green]" if ok else "[red]NEEDS FIX[/red]"
            console.print(f"{mark}  {f} [dim]{note}[/dim]")
        console.print("\n[bold]Stopped before submit.[/bold] Review in Chrome.")
        b.close()


if __name__ == "__main__":
    main()
