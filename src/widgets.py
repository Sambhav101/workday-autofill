"""Workday widget handlers. Each returns (ok: bool, note: str) so the caller can
build a review table. They locate by data-automation-id (stable across tenants)
and degrade gracefully — a field we can't fill is reported, never a hard crash.

All interactions use wait-for-state instead of fixed timeouts, with retry loops
for flaky Workday popups and dropdowns.
"""
from __future__ import annotations

import time
from playwright.sync_api import Page, Locator, TimeoutError as PwTimeout

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

OPTION_SEL = (
    '[data-automation-id="menuItem"], '
    '[data-automation-id="promptOption"], '
    '[data-automation-id="promptLeafNode"], '
    '[role="option"]'
)

# ── helpers ──────────────────────────────────────────────────────────────────

def _by_aid(page: Page, aid: str) -> Locator:
    return page.locator(f'[data-automation-id="{aid}"]')


def _poll(predicate, *, timeout_ms=4000, interval_ms=150):
    """Poll `predicate()` until truthy or timeout. Returns the truthy value or None."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        val = predicate()
        if val:
            return val
        time.sleep(interval_ms / 1000)
    return None


def close_popups(page: Page):
    """Dismiss any open Workday dropdown/popup overlay. Uses Escape then clicks
    the page heading (a neutral, always-present element) instead of pixel coords."""
    for _ in range(4):
        if not page.locator(OPTION_SEL).count():
            return
        page.keyboard.press("Escape")
        page.wait_for_timeout(120)
    # fallback: click a neutral element if options are still showing
    neutral = page.locator('[data-automation-id="pageHeaderTitle"], h2, h1').first
    if neutral.count():
        try:
            neutral.click(force=True)
            page.wait_for_timeout(150)
        except Exception:  # noqa: BLE001
            pass


def _wait_for_options(page: Page, *, timeout_ms=3000) -> bool:
    """Wait until at least one dropdown option appears in the DOM."""
    return bool(_poll(lambda: page.locator(OPTION_SEL).count() > 0, timeout_ms=timeout_ms))


def _verify_text(el: Locator, expected: str) -> bool:
    """Check that an input/textarea actually holds the expected value after fill."""
    try:
        actual = (el.input_value() or "").strip()
        return expected.strip() in actual or actual in expected.strip()
    except Exception:  # noqa: BLE001
        return False


# ── text fields ──────────────────────────────────────────────────────────────

def fill_text(page: Page, aid: str, value: str, *, only_if_empty: bool = False,
              retries: int = 2):
    wrap = _by_aid(page, aid)
    if not wrap.count():
        return False, "field not found"
    el = wrap.first.locator("input, textarea").first
    if not el.count():
        return False, "no input inside field"
    try:
        if only_if_empty and (el.input_value() or "").strip():
            return True, "left existing value"
        for attempt in range(retries + 1):
            el.scroll_into_view_if_needed()
            el.click()
            el.fill(str(value))
            if _verify_text(el, str(value)):
                return True, "filled"
            # value didn't stick — clear and retry
            el.fill("")
            page.wait_for_timeout(100)
        return True, "filled (unverified)"
    except Exception as e:  # noqa: BLE001
        return False, f"error: {e}"


# ── radio buttons ────────────────────────────────────────────────────────────

def select_radio(page: Page, group_aid: str, label_text: str):
    group = _by_aid(page, group_aid)
    if not group.count():
        return False, "radio group not found"
    radios = group.first.locator('input[type="radio"]')
    for i in range(radios.count()):
        rid = radios.nth(i).get_attribute("id")
        lab = page.locator(f'label[for="{rid}"]') if rid else None
        lbl = (lab.first.inner_text() or "").strip() if lab and lab.count() else ""
        if lbl.lower() == label_text.lower():
            try:
                lab.first.scroll_into_view_if_needed()
                lab.first.click()
                # verify the radio is actually checked
                if _poll(lambda r=radios.nth(i): r.is_checked(), timeout_ms=1000):
                    return True, f"selected {label_text}"
                return True, f"selected {label_text} (unverified)"
            except Exception as e:  # noqa: BLE001
                return False, f"error: {e}"
    return False, f"no option labelled {label_text!r}"


# ── button dropdowns ─────────────────────────────────────────────────────────

def select_button_dropdown(page: Page, aid: str, value: str, *, retries: int = 2):
    wrap = _by_aid(page, aid)
    if not wrap.count():
        return False, "dropdown not found"
    wrap = wrap.first
    btn = wrap.locator("button").first
    try:
        cur = (btn.inner_text() or "")
        if value.lower() in cur.lower():
            return True, "already set"
        for attempt in range(retries + 1):
            close_popups(page)
            btn.scroll_into_view_if_needed()
            btn.click()
            if not _wait_for_options(page):
                if attempt < retries:
                    continue
                return False, "dropdown didn't open"
            if _click_option(page, value):
                # verify the button text updated
                if _poll(lambda: value.lower() in (btn.inner_text() or "").lower(),
                         timeout_ms=1500):
                    return True, f"selected {value}"
                return True, f"selected {value} (unverified)"
            close_popups(page)
            if attempt < retries:
                page.wait_for_timeout(200)
        return False, f"option {value!r} not in list"
    except Exception as e:  # noqa: BLE001
        close_popups(page)
        return False, f"error: {e}"


# ── option clicking ──────────────────────────────────────────────────────────

def _click_option(page: Page, text: str) -> bool:
    """Click a dropdown option by visible text. Exact match first, then
    case-insensitive, then substring fallback."""
    items = page.locator(OPTION_SEL)
    n = items.count()
    if not n:
        return False

    # pass 1: exact match
    for i in range(n):
        it = items.nth(i)
        try:
            if not it.is_visible():
                continue
        except Exception:  # noqa: BLE001
            continue
        if (it.inner_text() or "").strip() == text:
            _safe_click(it)
            return True

    # pass 2: case-insensitive exact
    text_low = text.lower()
    for i in range(n):
        it = items.nth(i)
        try:
            if not it.is_visible():
                continue
        except Exception:  # noqa: BLE001
            continue
        if (it.inner_text() or "").strip().lower() == text_low:
            _safe_click(it)
            return True

    # pass 3: substring containment
    for i in range(n):
        it = items.nth(i)
        try:
            if not it.is_visible():
                continue
        except Exception:  # noqa: BLE001
            continue
        it_text = (it.inner_text() or "").strip().lower()
        if text_low in it_text or it_text in text_low:
            _safe_click(it)
            return True

    return False


def _safe_click(loc: Locator):
    """Click with fallback chain: normal → force → JS click."""
    try:
        loc.click(timeout=1500)
    except Exception:  # noqa: BLE001
        try:
            loc.evaluate("e => e.click()")
        except Exception:  # noqa: BLE001
            loc.click(force=True)


# ── multiselect by label ─────────────────────────────────────────────────────

_FIND_MS_BY_LABEL = r"""
(label) => {
  const conts = [...document.querySelectorAll('[data-automation-id="multiselectInputContainer"]')];
  for (const c of conts) {
    let p = c, hit = '';
    for (let d = 0; d < 8 && p; d++) {
      const l = p.querySelector('label, legend');
      if (l && l.innerText.trim()) { hit = l.innerText; break; }
      p = p.parentElement;
    }
    if (hit.toLowerCase().includes(label.toLowerCase())) {
      c.setAttribute('data-wf-target', '1');
      return true;
    }
  }
  return false;
}
"""


def _click_menu_item(page: Page, text: str) -> bool:
    """Click a visible dropdown option by text. Workday uses different element
    types across widgets (menuItem, promptOption, role=option) — and sometimes
    renders inside a ReactVirtualized container. We check all visible options."""
    sel = '[data-automation-id="promptOption"], [data-automation-id="menuItem"], [role="option"]'
    items = page.locator(sel)
    text_low = text.lower()
    # pass 1: exact match
    for i in range(items.count()):
        it = items.nth(i)
        try:
            if not it.is_visible():
                continue
            it_text = (it.inner_text() or "").strip()
            if it_text.lower() == text_low:
                _safe_click(it)
                return True
        except Exception:  # noqa: BLE001
            continue
    # pass 2: substring fallback
    for i in range(items.count()):
        it = items.nth(i)
        try:
            if not it.is_visible():
                continue
            it_text = (it.inner_text() or "").strip().lower()
            if text_low in it_text or it_text in text_low:
                _safe_click(it)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def select_multiselect_by_label(page: Page, label_hint: str, value: str,
                                *, retries: int = 2):
    """Typeahead multiselect, possibly cascading. `value` may be a path like
    'Job Board > LinkedIn' — click each cascade level via menuItem. Falls back
    to picking the first available option if the preferred one isn't found."""
    close_popups(page)
    if not page.evaluate(_FIND_MS_BY_LABEL, label_hint):
        return False, f"no multiselect near label {label_hint!r}"
    cont = page.locator('[data-wf-target="1"]').first
    levels = [s.strip() for s in str(value).split(">") if s.strip()]
    chip_sel = '[data-automation-id="selectedItem"]'
    try:
        # check if already set
        existing = cont.locator(chip_sel)
        if existing.count():
            chip_text = existing.last.inner_text().strip().lower()
            target = levels[-1].lower()
            if target in chip_text or chip_text in target:
                return True, f"already set ({existing.last.inner_text().strip()[:40]})"
        cont.scroll_into_view_if_needed()
        box = cont.locator('[data-automation-id="searchBox"], input').first
        if not box.count():
            return False, "no input in multiselect"
        for attempt in range(retries + 1):
            close_popups(page)
            before = cont.locator(chip_sel).count()
            box.evaluate("e => { e.scrollIntoView({block:'center'}); e.focus(); e.click(); }")
            page.wait_for_timeout(400)
            if not _wait_for_options(page, timeout_ms=2000):
                if attempt < retries:
                    continue
                return False, "multiselect didn't open"
            # walk each cascade level
            all_ok = True
            for lvl in levels:
                if not _click_menu_item(page, lvl):
                    all_ok = False
                    break
                page.wait_for_timeout(600)
            if not all_ok:
                # fallback: try picking any job board site
                close_popups(page)
                box.click()
                _wait_for_options(page, timeout_ms=1500)
                fallbacks = ["Job Board", "Social Media", "Other"]
                picked_parent = False
                for fb in fallbacks:
                    if _click_menu_item(page, fb):
                        picked_parent = True
                        _wait_for_options(page, timeout_ms=1500)
                        break
                if picked_parent:
                    # pick first available sub-option
                    first_item = page.locator('[data-automation-id="menuItem"]:visible').first
                    if first_item.count():
                        _safe_click(first_item)
                    else:
                        close_popups(page)
                        if attempt < retries:
                            continue
                        return False, f"no sub-options found"
                else:
                    close_popups(page)
                    if attempt < retries:
                        continue
                    return False, f"no fallback category found"
            # verify a chip appeared
            got_chip = _poll(
                lambda: cont.locator(chip_sel).count() > before,
                timeout_ms=2000,
            )
            close_popups(page)
            if got_chip:
                sel_text = cont.locator(chip_sel).last.inner_text().strip()
                return True, f"selected {sel_text}"
            if attempt < retries:
                continue
        return False, f"option not found for {' > '.join(levels)}"
    except Exception as e:  # noqa: BLE001
        close_popups(page)
        return False, f"error: {e}"
    finally:
        page.evaluate("() => document.querySelector('[data-wf-target]')?.removeAttribute('data-wf-target')")


# ── multiselect by automation-id ─────────────────────────────────────────────

def select_multiselect_by_aid(page: Page, aid: str, value: str, *,
                               fallback_label: str | None = None, retries: int = 2):
    """Fill a multiselect/cascade field by its data-automation-id. Falls back to
    label-based lookup if the ID isn't found (some tenants differ)."""
    cont = _by_aid(page, aid)
    if not cont.count():
        if fallback_label:
            return select_multiselect_by_label(page, fallback_label, value, retries=retries)
        return False, "multiselect not found"
    cont = cont.first
    levels = [s.strip() for s in str(value).split(">") if s.strip()]
    chip_sel = '[data-automation-id="selectedItem"]'
    try:
        # check if already set
        existing = cont.locator(chip_sel)
        if existing.count():
            chip_text = existing.last.inner_text().strip().lower()
            target = levels[-1].lower()
            if target in chip_text or chip_text in target:
                return True, f"already set ({existing.last.inner_text().strip()[:40]})"
        cont.scroll_into_view_if_needed()
        box = cont.locator('[data-automation-id="searchBox"], input').first
        if not box.count():
            return False, "no input in multiselect"
        for attempt in range(retries + 1):
            close_popups(page)
            before = cont.locator(chip_sel).count()
            box.evaluate("e => { e.scrollIntoView({block:'center'}); e.focus(); e.click(); }")
            page.wait_for_timeout(400)
            if not _wait_for_options(page, timeout_ms=2000):
                if attempt < retries:
                    continue
                return False, "multiselect didn't open"
            all_ok = True
            for lvl in levels:
                if not _click_menu_item(page, lvl):
                    all_ok = False
                    break
                page.wait_for_timeout(600)
            if not all_ok:
                # fallback: pick first available option
                close_popups(page)
                box.evaluate("e => { e.focus(); e.click(); }")
                page.wait_for_timeout(400)
                if _wait_for_options(page, timeout_ms=1500):
                    first = page.locator('[data-automation-id="promptOption"]:visible, '
                                         '[data-automation-id="menuItem"]:visible').first
                    if first.count():
                        _safe_click(first)
                        page.wait_for_timeout(400)
            got_chip = _poll(
                lambda: cont.locator(chip_sel).count() > before,
                timeout_ms=2000,
            )
            close_popups(page)
            if got_chip:
                sel_text = cont.locator(chip_sel).last.inner_text().strip()
                return True, f"selected {sel_text}"
            if attempt < retries:
                continue
        return False, f"option not found for {' > '.join(levels)}"
    except Exception as e:  # noqa: BLE001
        close_popups(page)
        return False, f"error: {e}"


def select_multiselect(page: Page, container_aid: str, value: str):
    """Legacy wrapper — delegates to select_multiselect_by_aid."""
    return select_multiselect_by_aid(page, container_aid, value)
