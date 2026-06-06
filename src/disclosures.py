"""Fill the Workday Voluntary Disclosures / EEO page from profile.yaml's
`sensitive` section (gender, ethnicity, veteran status) + accept the terms box.
These are user-set values only — never guessed. Stops before submit.

    ./venv/bin/python -m src.disclosures
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright, Page
from rich.console import Console
from rich.table import Table

from . import browser
from .widgets import close_popups, _wait_for_options, _safe_click, _poll, OPTION_SEL
from .profile import load_profile

console = Console()


def _pick_visible(page: Page, value: str):
    """Among currently VISIBLE options, return the locator matching `value`."""
    items = page.locator(OPTION_SEL)
    vis = []
    for i in range(items.count()):
        it = items.nth(i)
        try:
            if it.is_visible():
                vis.append((it, (it.inner_text() or "").strip()))
        except Exception:  # noqa: BLE001
            pass
    vlow = value.lower()
    # exact match
    for it, t in vis:
        if t.lower() == vlow:
            return it
    # substring match
    for it, t in vis:
        if vlow in t.lower() or t.lower() in vlow:
            return it
    # keyword match — all significant words from value appear in option
    keywords = [w for w in vlow.split() if len(w) > 2 and w not in ("the", "and", "for")]
    if keywords:
        for it, t in vis:
            tlow = t.lower()
            if all(k in tlow for k in keywords):
                return it
    return None


def _select(page: Page, aid: str, want: str, *, retries: int = 2) -> tuple:
    wrap = page.locator(f'[data-automation-id="{aid}"]')
    if not wrap.count():
        return False, "field not on page"
    if not want:
        return None, "blank in profile — skipped"
    for attempt in range(retries + 1):
        try:
            close_popups(page)
            wrap.first.locator("button").first.scroll_into_view_if_needed()
            wrap.first.locator("button").first.click()
            if not _wait_for_options(page):
                if attempt < retries:
                    continue
                return False, "dropdown didn't open"
            opt = _pick_visible(page, want)
            if opt is None:
                close_popups(page)
                if attempt < retries:
                    continue
                return False, f"no option ~ {want!r}"
            txt = opt.inner_text().strip()
            _safe_click(opt)
            page.wait_for_timeout(200)
            close_popups(page)
            return True, txt[:40]
        except Exception as e:  # noqa: BLE001
            close_popups(page)
            if attempt < retries:
                continue
            return False, f"error: {e}"
    return False, f"failed after {retries + 1} attempts"


def _select_checkbox(page: Page, aid: str, want: str) -> tuple:
    """Select a checkbox option inside a checkbox group field."""
    wrap = page.locator(f'[data-automation-id="{aid}"]')
    if not wrap.count():
        return False, "field not on page"
    if not want:
        return None, "blank in profile — skipped"
    lbl = wrap.locator("label", has_text=want)
    if not lbl.count():
        return False, f"no checkbox label ~ {want!r}"
    try:
        lbl.first.scroll_into_view_if_needed()
        fid = lbl.first.get_attribute("for")
        box = page.locator(f'[id="{fid}"]') if fid else None
        if box and box.count() and not box.first.is_checked():
            box.first.check()
        else:
            lbl.first.click()
        return True, want
    except Exception as e:  # noqa: BLE001
        return False, f"error: {e}"


def fill_disclosures(page: Page):
    p = load_profile().get("sensitive", {})
    veteran = p.get("veteran_status", "")

    # Dropdowns — try multiple automation IDs per concept (varies by tenant)
    DROPDOWN_FIELDS = [
        ("Gender", ["formField-gender"], p.get("gender", "")),
        ("Hispanic/Latino", ["formField-hispanicOrLatino"], p.get("hispanic_latino", "")),
        ("Ethnicity", ["formField-ethnicity"], p.get("race_ethnicity", "")),
        ("Veteran status", ["formField-veteranStatus", "formField-veteranClassification",
                            "formField-protectedVeteranType"], veteran),
    ]
    results = []
    for label, aids, want in DROPDOWN_FIELDS:
        filled = False
        for aid in aids:
            if page.locator(f'[data-automation-id="{aid}"]').count():
                ok, note = _select(page, aid, want)
                results.append((label, want or "—", ok, note))
                filled = True
                break
        if not filled:
            pass  # field not on this tenant — skip silently

    # Checkbox group for race (some tenants use ethnicityMulti instead of ethnicity dropdown)
    race_field = page.locator('[data-automation-id="formField-ethnicityMulti"]')
    if race_field.count():
        race = p.get("race_ethnicity", "")
        ok, note = _select_checkbox(page, "formField-ethnicityMulti", race)
        results.append(("Race", race or "—", ok, note))

    # Accept terms checkbox
    cb = page.locator('[data-automation-id="formField-acceptTermsAndAgreements"] input')
    if cb.count():
        try:
            if not cb.first.is_checked():
                cb.first.scroll_into_view_if_needed()
                cb.first.check()
            results.append(("Accept terms", "checked", True, "checked"))
        except Exception as e:  # noqa: BLE001
            results.append(("Accept terms", "checked", False, f"error: {e}"))
    return results


def main():
    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_workday_tab(b)
        if not page:
            console.print("[red]No Workday tab open.[/red]")
            return
        results = fill_disclosures(page)
        t = Table(title="Voluntary Disclosures — review (nothing submitted)")
        t.add_column("Field"); t.add_column("Value"); t.add_column("Result")
        for f, v, ok, note in results:
            mark = "[green]ok[/green]" if ok else ("[dim]skip[/dim]" if ok is None else "[red]NEEDS FIX[/red]")
            t.add_row(f, str(v), f"{mark} [dim]{note}[/dim]")
        console.print(t)
        console.print("\n[bold]Stopped before submit.[/bold] Review in Chrome.")
        b.close()


if __name__ == "__main__":
    main()
