"""Fill the Workday "My Information" page from profile.yaml, then print a review
table and STOP (no navigation, no submit).

Per-field correction without an interactive prompt:
    ./venv/bin/python -m src.fill                       # fill everything + review
    ./venv/bin/python -m src.fill --set city="New York" # refill just one field
    ./venv/bin/python -m src.fill --set state=NJ --set postal_code=07030

Field keys: previous_worker, first_name, last_name, country, address1, city,
state, postal_code, email, phone_type, phone_number, how_did_you_hear,
country_phone_code.
"""
from __future__ import annotations

import argparse
from playwright.sync_api import sync_playwright, Page
from rich.console import Console
from rich.table import Table

from . import browser, widgets
from .widgets import close_popups
from .discover import discover_fields
from .profile import load_profile

console = Console()


def build_specs(p: dict) -> dict:
    """Map of field key -> {target aid, desired value, label}.

    Does NOT include widget type — that comes from discover_fields() at runtime,
    because the same field can be a dropdown on one tenant and a multiselect on
    another (pattern #6).
    """
    ident, contact, prefs = p["identity"], p["contact"], p.get("preferences", {})
    state_full = widgets.US_STATES.get(str(contact.get("state", "")).upper(), contact.get("state", ""))
    return {
        "previous_worker": {"label": "Previously worked here?",
                             "target": "formField-candidateIsPreviousWorker", "value": "No"},
        "first_name":  {"label": "First Name",
                        "target": "formField-legalName--firstName", "value": ident["first_name"]},
        "last_name":   {"label": "Last Name",
                        "target": "formField-legalName--lastName", "value": ident["last_name"]},
        "country":     {"label": "Country",
                        "target": "formField-country", "value": "United States of America"},
        "address1":    {"label": "Address Line 1",
                        "target": "formField-addressLine1", "value": contact.get("address_line1", "")},
        "city":        {"label": "City",
                        "target": "formField-city", "value": contact.get("city", "")},
        "state":       {"label": "State",
                        "target": "formField-countryRegion", "value": state_full},
        "postal_code": {"label": "Postal Code",
                        "target": "formField-postalCode", "value": str(contact.get("postal_code", ""))},
        "email":       {"label": "Email", "only_if_empty": True,
                        "target": "formField-emailAddress", "value": ident["email"]},
        "phone_type":  {"label": "Phone Device Type",
                        "target": "formField-phoneType", "value": "Mobile"},
        "phone_number": {"label": "Phone Number",
                         "target": "formField-phoneNumber", "value": str(ident.get("phone", ""))},
        "how_did_you_hear": {"label": "How Did You Hear About Us?",
                             "target": "formField-source", "value": prefs.get("how_did_you_hear", "")},
        "country_phone_code": {"label": "Country Phone Code",
                               "target": "formField-countryPhoneCode", "value": "United States of America (+1)"},
        "phone_extension": {"label": "Phone Extension",
                            "target": "formField-extension", "value": ""},
    }


def _apply_by_widget(page: Page, target: str, value: str, widget: str, **kwargs):
    """Dispatch to the right widget function based on the discovered widget type."""
    if value == "" and widget != "text":
        return None, "skipped (no value)"
    if widget == "text":
        if value == "":
            return None, "skipped (no value)"
        return widgets.fill_text(page, target, value, only_if_empty=kwargs.get("only_if_empty", False))
    if widget == "radio":
        return widgets.select_radio(page, target, value)
    if widget == "dropdown":
        return widgets.select_button_dropdown(page, target, value)
    if widget == "multiselect":
        return widgets.select_multiselect_by_aid(page, target, value)
    if widget == "checkbox":
        return None, "skipped (checkbox)"
    return False, f"unknown widget type '{widget}'"


_PHONE_TYPE_PREFERENCES = ["Mobile", "Home"]


def _fill_phone_type(page: Page, target: str, value: str):
    """Fill phone device type — try Mobile, then Home, then first available."""
    ok, note = widgets.select_button_dropdown(page, target, value)
    if ok:
        return ok, note
    for fallback in _PHONE_TYPE_PREFERENCES:
        if fallback.lower() == value.lower():
            continue
        ok, note = widgets.select_button_dropdown(page, target, fallback)
        if ok:
            return ok, f"fallback: {note}"
    # Last resort: pick the first option
    from .widgets import _safe_click, _wait_for_options, OPTION_SEL, close_popups
    wrap = page.locator(f'[data-automation-id="{target}"]')
    if not wrap.count():
        return False, "field not found"
    btn = wrap.first.locator("button").first
    btn.scroll_into_view_if_needed()
    btn.click()
    if _wait_for_options(page):
        first = page.locator(OPTION_SEL).first
        if first.count() and first.is_visible():
            txt = first.inner_text().strip()
            _safe_click(first)
            return True, f"first option: {txt}"
    close_popups(page)
    return False, "no phone type options available"


_SOURCE_PREFERENCES = ["linkedin", "job board", "internet", "website", "online", "other"]
_SOURCE_PLACEHOLDERS = {"", "select one", "—", "--"}


def _source_collect_options(page: Page) -> list[str]:
    """Return visible dropdown options currently rendered for the source field."""
    return page.evaluate("""() => {
        const sels = ['[data-automation-id="menuItem"]',
                       '[data-automation-id="promptOption"]',
                       '[role="option"]'];
        const results = [];
        for (const sel of sels) {
            for (const el of document.querySelectorAll(sel)) {
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.top > 0 && r.top < window.innerHeight) {
                    const txt = (el.innerText || '').trim();
                    if (txt && !['Select One', '—', '--'].includes(txt)) {
                        results.push(txt);
                    }
                }
            }
        }
        return [...new Set(results)];
    }""")


def _source_first_unresolved_control(page: Page, target: str):
    """Return the first visible unresolved dropdown/input inside the source field.

    Some tenants render "How Did You Hear About Us?" as a cascade:
    one dropdown selection reveals another blank dropdown in the same wrapper.
    This helper finds the next blank control, if any, so the filler can walk the
    chain one step at a time.
    """
    wrap = page.locator(f'[data-automation-id="{target}"]')
    if not wrap.count():
        return None

    wrap = wrap.first
    buttons = wrap.locator('button[aria-haspopup="listbox"]')
    for i in range(buttons.count()):
        btn = buttons.nth(i)
        try:
            if not btn.is_visible():
                continue
            txt = (btn.inner_text() or "").strip().lower()
            if txt in _SOURCE_PLACEHOLDERS:
                return ("button", btn)
        except Exception:  # noqa: BLE001
            continue

    inputs = wrap.locator("input")
    for i in range(inputs.count()):
        inp = inputs.nth(i)
        try:
            if inp.is_visible():
                return ("input", inp)
        except Exception:  # noqa: BLE001
            continue
    return None


def _source_open_control(control):
    kind, loc = control
    if kind == "button":
        loc.scroll_into_view_if_needed()
        loc.click()
        return True
    try:
        loc.evaluate("e => { e.scrollIntoView({block:'center'}); e.focus(); e.click(); }")
        return True
    except Exception:  # noqa: BLE001
        return False


def _fill_source(page: Page, target: str):
    """Fill 'How Did You Hear About Us'.

    The field can be a single dropdown or a cascade where each selection reveals
    the next dropdown. We walk the chain until no unresolved dropdown remains.
    """
    from .widgets import _wait_for_options, _click_option

    if not page.locator(f'[data-automation-id="{target}"]').count():
        return False, "field not found"

    levels = 0
    chosen: list[str] = []

    while levels < 4:
        control = _source_first_unresolved_control(page, target)
        if not control:
            break

        if not _source_open_control(control):
            close_popups(page)
            return False, "couldn't open source dropdown"

        if not _wait_for_options(page):
            close_popups(page)
            return False, "dropdown didn't open"

        options = _source_collect_options(page)
        if not options:
            close_popups(page)
            return False, "no options available"

        if levels == 0:
            picked = None
            for pref in _SOURCE_PREFERENCES:
                for txt in options:
                    if pref in txt.lower():
                        picked = txt
                        break
                if picked:
                    break
            if picked is None:
                picked = options[0]
        else:
            picked = options[0]

        ok = _click_option(page, picked)
        if not ok:
            close_popups(page)
            return False, f"couldn't select {picked!r}"

        chosen.append(picked[:40])
        levels += 1
        page.wait_for_timeout(400)

    if not chosen:
        return False, "couldn't select any option"
    if levels > 1:
        return True, f"cascaded source path ({levels} levels): {' > '.join(chosen)}"
    return True, f"picked: {chosen[0]}"


def render(results: list[tuple]):
    t = Table(title="My Information — review (nothing submitted)")
    t.add_column("#", justify="right")
    t.add_column("Field")
    t.add_column("Value")
    t.add_column("Result")
    for i, (key, spec, ok, note) in enumerate(results, 1):
        if ok is True:
            mark = "[green]ok[/green]"
        elif ok is None:
            mark = "[dim]skip[/dim]"
        else:
            mark = "[red]NEEDS FIX[/red]"
        t.add_row(str(i), f"{spec['label']}\n[dim]{key}[/dim]",
                  str(spec["value"]) or "[dim]—[/dim]", f"{mark}  [dim]{note}[/dim]")
    console.print(t)
    bad = [r for r in results if r[2] is False]
    if bad:
        console.print(f"\n[yellow]{len(bad)} field(s) need attention.[/yellow] "
                      "Fix in Chrome, or re-run with --set key=value.")
    console.print("\n[bold]Stopped before any navigation/submit.[/bold] Review in Chrome.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[], metavar="key=value",
                    help="refill only these fields (repeatable)")
    args = ap.parse_args()

    profile = load_profile()
    specs = build_specs(profile)

    overrides = {}
    for item in args.set:
        if "=" not in item:
            ap.error(f"--set expects key=value, got {item!r}")
        k, v = item.split("=", 1)
        if k not in specs:
            ap.error(f"unknown field key {k!r}. Valid: {', '.join(specs)}")
        overrides[k] = v

    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_workday_tab(b)
        if not page:
            console.print("[red]No Workday tab open.[/red] Open the application page in Chrome.")
            return
        results = fill_my_information(page, overrides)
        render(results)
        b.close()


def fill_my_information(page: Page, overrides: dict | None = None):
    overrides = overrides or {}
    specs = build_specs(load_profile())

    # Discover what's actually on the page: widget types and current values
    discovered = discover_fields(page)
    disc_by_aid = {f["aid"]: f for f in discovered}

    results = []
    for key, spec in specs.items():
        target = spec["target"]
        disc = disc_by_aid.get(target)

        # Field doesn't exist on this tenant — skip
        if not disc or not disc.get("visible"):
            if key in overrides:
                results.append((key, spec, False, "field not found on page"))
            continue

        # Already filled and not overridden — skip (pattern #5, #20)
        # "Select One", "—", "--" are placeholder text, not real values
        real_value = disc["value"]
        if real_value.lower() in ("select one", "—", "--", ""):
            real_value = ""
        if real_value and key not in overrides:
            results.append((key, spec, None, f"already set: {disc['value'][:40]}"))
            continue

        value = overrides.get(key, spec["value"])
        spec = dict(spec, value=value)

        close_popups(page)
        if key == "how_did_you_hear":
            ok, note = _fill_source(page, target)
        elif key == "phone_type":
            ok, note = _fill_phone_type(page, target, value)
        else:
            ok, note = _apply_by_widget(
                page, target, value, disc["widget"],
                only_if_empty=spec.get("only_if_empty", False),
            )
        results.append((key, spec, ok, note))
    return results


if __name__ == "__main__":
    main()
