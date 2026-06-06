"""Fill the Workday "My Experience" page: work history, education, skills,
LinkedIn — from profile.yaml. Adds entry blocks as needed, then STOPS (no submit).

    ./venv/bin/python -m src.experience            # fill everything + review
    ./venv/bin/python -m src.experience --section work       # only one section
    ./venv/bin/python -m src.experience --section education
    ./venv/bin/python -m src.experience --section skills
    ./venv/bin/python -m src.experience --section links
"""
from __future__ import annotations

import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Locator
from rich.console import Console
from rich.table import Table

from . import browser, widgets
from .widgets import close_popups, _poll, _safe_click, _click_option, OPTION_SEL
from .profile import load_profile

console = Console()
results: list[tuple] = []


def log(name, ok, note):
    results.append((name, ok, note))


def _as_text(b):
    if isinstance(b, dict):
        return "; ".join(f"{k}: {v}" for k, v in b.items())
    return str(b)


def _ymd(val):
    s = str(val)
    parts = s.split("-")
    return parts[0], (parts[1] if len(parts) > 1 else None)


def fill_date(page: Page, container: Locator, value) -> tuple:
    if not container.count():
        return False, "date field missing"
    year, month = _ymd(value)
    try:
        if month:
            m = container.locator('[data-automation-id="dateSectionMonth-input"]').first
            if m.count():
                m.evaluate("e=>e.scrollIntoView({block:'center'})")
                m.evaluate("e=>e.focus()")
                page.keyboard.type(month, delay=60)
                page.wait_for_timeout(150)
        y = container.locator('[data-automation-id="dateSectionYear-input"]').first
        y.evaluate("e=>e.focus()")
        page.keyboard.type(year, delay=60)
        page.wait_for_timeout(150)
        return True, f"{value}"
    except Exception as e:  # noqa: BLE001
        return False, f"error: {e}"


def _text_nth(page: Page, aid: str, idx: int, value) -> tuple:
    wrap = page.locator(f'[data-automation-id="{aid}"]').nth(idx)
    if not wrap.count():
        return False, "field missing"
    el = wrap.locator("input, textarea").first
    try:
        el.evaluate("e=>e.scrollIntoView({block:'center'})")
        el.click()
        el.fill(str(value))
        if widgets._verify_text(el, str(value)):
            return True, "filled"
        # retry once
        el.fill("")
        el.fill(str(value))
        return True, "filled"
    except Exception as e:  # noqa: BLE001
        return False, f"error: {e}"


def ensure_blocks(page: Page, anchor_aid: str, add_index: int, needed: int):
    adds = page.locator('[data-automation-id="add-button"]')
    current = page.locator(f'[data-automation-id="{anchor_aid}"]').count()
    if current >= needed:
        return
    for _ in range(needed - current):
        if adds.count() <= add_index:
            break
        adds.nth(add_index).scroll_into_view_if_needed()
        adds.nth(add_index).click()
        _poll(
            lambda: page.locator(f'[data-automation-id="{anchor_aid}"]').count() > current,
            timeout_ms=3000,
        )


def fill_work(page: Page, jobs: list[dict]):
    existing = page.locator('[data-automation-id="formField-jobTitle"]').count()
    if existing >= len(jobs):
        first_val = ""
        inp = page.locator('[data-automation-id="formField-jobTitle"]').first.locator("input, textarea").first
        if inp.count():
            first_val = (inp.input_value() or "").strip()
        if first_val:
            log("work", True, f"already filled ({existing} entries)")
            return
    ensure_blocks(page, "formField-jobTitle", 0, len(jobs))
    for i, job in enumerate(jobs):
        log(f"work[{i}] title", *_text_nth(page, "formField-jobTitle", i, job["title"]))
        log(f"work[{i}] company", *_text_nth(page, "formField-companyName", i, job["company"]))
        if job.get("location"):
            log(f"work[{i}] location", *_text_nth(page, "formField-location", i, job["location"]))
        sd = page.locator('[data-automation-id="formField-startDate"]').nth(i)
        log(f"work[{i}] from", *fill_date(page, sd, job["start"]))
        if job.get("current"):
            cb = page.locator('[data-automation-id="formField-currentlyWorkHere"]').nth(i).locator("input")
            if cb.count() and not cb.first.is_checked():
                cb.first.check()
        elif job.get("end"):
            ed = page.locator('[data-automation-id="formField-endDate"]').nth(i)
            log(f"work[{i}] to", *fill_date(page, ed, job["end"]))
        desc = "\n".join(_as_text(b) for b in job.get("bullets", []))
        if desc:
            log(f"work[{i}] description", *_text_nth(page, "formField-roleDescription", i, desc))


def _school_aid(page: Page) -> str:
    if page.locator('[data-automation-id="formField-school"]').count():
        return "formField-school"
    return "formField-schoolName"


def _school_widget_type(page: Page, aid: str) -> str:
    """Check if the school field is a text input or a searchable multiselect."""
    wrap = page.locator(f'[data-automation-id="{aid}"]').first
    if wrap.locator('[data-automation-id="multiselectInputContainer"], [data-automation-id="searchBox"]').count():
        return "multiselect"
    return "text"


SCHOOL_SEARCH_TERMS = {
    "stony brook university - suny": "Stony Brook",
    "stony brook university": "Stony Brook",
    "st. joseph's college new york": "Saint Josephs",
    "st. josephs college new york": "Saint Josephs",
    "saint joseph's college new york": "Saint Josephs",
}

SCHOOL_PICK_NAMES = {
    "stony brook university - suny": "Stony Brook University",
    "stony brook university": "Stony Brook University",
    "st. joseph's college new york": "Saint Josephs College-Main Campus",
    "st. josephs college new york": "Saint Josephs College-Main Campus",
    "saint joseph's college new york": "Saint Josephs College-Main Campus",
}


def _fill_school_multiselect(page: Page, aid: str, idx: int, school_name: str) -> tuple:
    """Fill school field when it's a searchable multiselect (formField-school)."""
    wrap = page.locator(f'[data-automation-id="{aid}"]').nth(idx)
    if not wrap.count():
        return False, "field missing"
    chip_sel = '[data-automation-id="selectedItem"]'
    if wrap.locator(chip_sel).count():
        existing = wrap.locator(chip_sel).first.inner_text().strip()
        return True, f"already set: {existing}"

    search_term = SCHOOL_SEARCH_TERMS.get(school_name.lower(), school_name.split(" - ")[0].split(",")[0].strip())
    pick_name = SCHOOL_PICK_NAMES.get(school_name.lower())

    box = wrap.locator("input").first
    box.evaluate("e=>e.scrollIntoView({block:'center'})")
    box.evaluate("e => { e.focus(); e.click(); }")
    page.wait_for_timeout(200)
    page.keyboard.type(search_term, delay=50)
    page.keyboard.press("Enter")
    _poll(lambda: page.locator(OPTION_SEL).count() > 0, timeout_ms=3000)
    page.wait_for_timeout(400)

    if pick_name:
        picked = _best_field_match(page, pick_name)
        if picked:
            close_popups(page)
            return True, f"{school_name} -> {picked}"

    # Fallback: best keyword match against the school name
    picked = _best_field_match(page, school_name)
    if picked:
        close_popups(page)
        return True, f"{school_name} -> {picked}"

    # No blind first-option fallback — wrong school is worse than no school
    close_popups(page)
    return False, f"no matching option for '{search_term}'"


def _edu_fully_filled(page: Page, aid: str, school_widget: str, count: int) -> bool:
    """Check if all education entries have school AND degree filled."""
    for i in range(count):
        # Check school
        school_wrap = page.locator(f'[data-automation-id="{aid}"]').nth(i)
        if school_widget == "multiselect":
            if not school_wrap.locator('[data-automation-id="selectedItem"]').count():
                return False
        else:
            inp = school_wrap.locator("input, textarea").first
            if not inp.count() or not (inp.input_value() or "").strip():
                return False
        # Check degree
        deg = page.locator('[data-automation-id="formField-degree"]').nth(i)
        if deg.count():
            btn = deg.locator("button").first
            if btn.inner_text().strip() in ("Select One", "—", "--", ""):
                return False
    return True


def fill_education(page: Page, schools: list[dict]):
    aid = _school_aid(page)
    school_widget = _school_widget_type(page, aid)
    existing = page.locator(f'[data-automation-id="{aid}"]').count()
    if existing >= len(schools) and _edu_fully_filled(page, aid, school_widget, len(schools)):
        log("education", True, f"already filled ({existing} entries)")
        return
    ensure_blocks(page, aid, 1, len(schools))
    for i, ed in enumerate(schools):
        if school_widget == "multiselect":
            log(f"edu[{i}] school", *_fill_school_multiselect(page, aid, i, ed["school"]))
        else:
            log(f"edu[{i}] school", *_text_nth(page, aid, i, ed["school"]))
        deg_wrap = page.locator('[data-automation-id="formField-degree"]').nth(i)
        deg_raw = str(ed.get("degree", "")).strip()
        if deg_wrap.count():
            btn = deg_wrap.locator("button").first
            try:
                close_popups(page)
                btn.scroll_into_view_if_needed()
                btn.click()
                if widgets._wait_for_options(page):
                    picked = _pick_degree(page, deg_raw)
                    if picked:
                        close_popups(page)
                        log(f"edu[{i}] degree", True, picked)
                    else:
                        close_popups(page)
                        log(f"edu[{i}] degree", False, f"no option ~ {deg_raw!r}")
                else:
                    close_popups(page)
                    log(f"edu[{i}] degree", False, "dropdown didn't open")
            except Exception as e:  # noqa: BLE001
                close_popups(page)
                log(f"edu[{i}] degree", False, f"error: {e}")
        if ed.get("field"):
            ok, note = _multiselect_nth(page, "formField-fieldOfStudy", i, ed["field"])
            log(f"edu[{i}] field", ok, note)
        if ed.get("gpa"):
            log(f"edu[{i}] gpa", *_text_nth(page, "formField-gradeAverage", i, ed["gpa"]))
        fy = page.locator('[data-automation-id="formField-firstYearAttended"]').nth(i)
        log(f"edu[{i}] from-year", *fill_date(page, fy, _ymd(ed["start"])[0]))
        ly = page.locator('[data-automation-id="formField-lastYearAttended"]').nth(i)
        log(f"edu[{i}] to-year", *fill_date(page, ly, _ymd(ed["end"])[0]))


# ── degree matching ──────────────────────────────────────────────────────────
# Workday tenants use wildly different labels for the same degree level.
DEGREE_VARIANTS = {
    "master": [
        "Masters of Science (MS)", "Master of Science (MS)",
        "Master of Science (M.S.)", "Masters of Science (M.S.)",
        "Masters of Science", "Master of Science",
        "Master's", "Masters", "Master's Degree", "Masters Degree",
        "M.S.", "MS",
    ],
    "bachelor": [
        "Bachelor of Science (BS)", "Bachelors of Science (BS)",
        "Bachelor of Science (B.S.)", "Bachelors of Science (B.S.)",
        "Bachelor of Science", "Bachelors of Science",
        "Bachelor's", "Bachelors", "Bachelor's Degree", "Bachelors Degree",
        "B.S.", "BS",
    ],
    "doctorate": [
        "Doctor of Philosophy (PhD)", "Doctor of Philosophy",
        "Doctorate", "Ph.D.", "PhD", "Other PhD",
    ],
    "associate": [
        "Associate of Science (AS)", "Associate of Science",
        "Associate's", "Associates", "A.S.", "AS", "Other Associate",
    ],
    "mba": [
        "Masters of Business Administration (MBA)",
        "Master of Business Administration (MBA)",
        "MBA",
    ],
    "high school": [
        "High School (High School)", "High School", "High School Diploma",
        "General Equivalency Diploma (GED)", "GED",
    ],
}


def _degree_level(raw: str) -> str:
    """Normalize a degree string to its level key."""
    r = raw.lower().replace("'", "").replace("'", "")
    if "mba" in r:
        return "mba"
    if "doctor" in r or "ph" in r:
        return "doctorate"
    if "master" in r:
        return "master"
    if "bachelor" in r:
        return "bachelor"
    if "associate" in r:
        return "associate"
    if "high school" in r or "ged" in r:
        return "high school"
    return r


_DEGREE_KEYWORDS = {"master", "bachelor", "associate", "doctor", "phd", "ph.d",
                     "mba", "high school", "ged", "diploma", "certificate",
                     "degree", "juris", "apprenticeship", "post-graduate"}
_DEGREE_EXACT = {"bs", "ba", "ms", "ma", "aa", "as", "jd", "md", "hs", "mas",
                 "b.s.", "b.a.", "m.s.", "m.a.", "a.a.", "a.s.", "j.d.", "m.d."}
_DEGREE_EXCLUDE = {"arts", "engineering", "eng.", "technology", "tech.",
                   "administration", "health", "medicine", "legal",
                   "business", "tax"}


def _is_degree_option(text: str) -> bool:
    """True if text looks like a degree label (not a school/field name),
    and does not contain excluded words like arts, engineering, etc."""
    t = text.lower().replace("’", "").replace("’", "")
    if t in _DEGREE_EXACT or t.rstrip(".") in _DEGREE_EXACT:
        return True
    if not any(k in t for k in _DEGREE_KEYWORDS):
        return False
    if any(x in t for x in _DEGREE_EXCLUDE):
        return False
    return True


def _pick_degree(page: Page, raw: str) -> str | None:
    """Find and click the best matching degree from visible options.
    Filters out non-degree options (school names, fields of study) that
    leak through because OPTION_SEL is global, and excludes degrees
    containing arts, engineering, etc."""
    items = page.locator(OPTION_SEL)
    texts = []
    for i in range(items.count()):
        try:
            it = items.nth(i)
            if not it.is_visible():
                continue
            t = (it.inner_text() or "").strip()
            if not t or t == "Select One":
                continue
            if not _is_degree_option(t):
                continue
            texts.append((it, t))
        except Exception:  # noqa: BLE001
            pass
    if not texts:
        return None
    level = _degree_level(raw)
    variants = DEGREE_VARIANTS.get(level, [raw])
    # match in variant priority order (first variant = best match)
    for v in variants:
        v_norm = v.lower().replace("'", "").replace("’", "")
        for loc, t in texts:
            t_norm = t.lower().replace("'", "").replace("’", "")
            if v_norm == t_norm:
                _safe_click(loc)
                return t
    # substring: variant text appears inside the option
    for v in variants:
        v_norm = v.lower().replace("'", "").replace("’", "")
        for loc, t in texts:
            t_norm = t.lower().replace("'", "").replace("’", "")
            if v_norm in t_norm:
                _safe_click(loc)
                return t
    return None


_STOP = {"and", "of", "the", "in", "for", "a", "science", "sciences", "studies", "general"}


def _keyword(value: str) -> str:
    for w in value.lower().split():
        if len(w) > 2 and w not in _STOP:
            return w
    return value.lower().split()[0] if value.split() else value.lower()


def _best_option(page: Page, value: str) -> str | None:
    items = page.locator(OPTION_SEL)
    n = items.count()
    if not n:
        return None
    texts = []
    for i in range(n):
        try:
            t = (items.nth(i).inner_text() or "").strip()
            if t and items.nth(i).is_visible():
                texts.append(t)
        except Exception:  # noqa: BLE001
            pass
    vlow = value.lower()
    for t in texts:
        if t.lower() == vlow:
            return t
    key = _keyword(value)
    cand = [t for t in texts if key in t.lower()]
    if not cand:
        return None
    for t in cand:
        if vlow in t.lower() or t.lower() in vlow:
            return t
    vwords = set(vlow.split())
    cand.sort(key=lambda t: (-len(vwords & set(t.lower().split())), len(t)))
    return cand[0]


def _clear_multiselect(page: Page, wrap: Locator):
    for _ in range(8):
        chips = wrap.locator('[data-automation-id="DELETE_charm"], '
                             'button[aria-label^="Delete"], '
                             '[data-automation-id="selectedItem"] button')
        if not chips.count():
            break
        try:
            chips.first.click()
            page.wait_for_timeout(150)
        except Exception:  # noqa: BLE001
            break


# Field of study can appear under different names across tenants.
FIELD_VARIANTS = {
    "computer science": [
        "Computer Science", "Computer Sciences",
        "Computer and Information Science", "Computer and Information Sciences",
    ],
    "mathematics": [
        "Mathematics",
    ],
    "computer science and mathematics": [
        "Computer Science and Mathematics", "Mathematics and Computer Science",
        "Computer Science", "Computer Sciences",
        "Computer and Information Science", "Computer and Information Sciences",
        "Mathematics",
    ],
}


def _best_field_match(page: Page, value: str) -> str | None:
    """Find the best matching option from visible results.
    Matches strictly against FIELD_VARIANTS — no fuzzy/keyword fallback.
    Prefers promptLeafNode, falls back to OPTION_SEL."""
    leaf_sel = '[data-automation-id="promptLeafNode"]'
    items = page.locator(leaf_sel)
    vis = []
    for i in range(items.count()):
        it = items.nth(i)
        try:
            if it.is_visible():
                vis.append((it, (it.inner_text() or "").strip()))
        except Exception:  # noqa: BLE001
            pass
    if not vis:
        items = page.locator(OPTION_SEL)
        for i in range(items.count()):
            it = items.nth(i)
            try:
                if it.is_visible():
                    vis.append((it, (it.inner_text() or "").strip()))
            except Exception:  # noqa: BLE001
                pass
    if not vis:
        return None
    vlow = value.lower()
    # exact match
    for loc, t in vis:
        if t.lower() == vlow:
            _safe_click(loc)
            return t
    # known variants — tried in order (first = best match)
    variants = FIELD_VARIANTS.get(vlow, [])
    for v in variants:
        for loc, t in vis:
            if t.lower() == v.lower():
                _safe_click(loc)
                return t
    return None


def _multiselect_nth(page: Page, aid: str, idx: int, value: str,
                     *, clear: bool = True, retries: int = 2) -> tuple:
    wrap = page.locator(f'[data-automation-id="{aid}"]').nth(idx)
    if not wrap.count():
        return False, "field missing"
    chip_sel = '[data-automation-id="selectedItem"]'
    for attempt in range(retries + 1):
        try:
            close_popups(page)
            if clear:
                _clear_multiselect(page, wrap)
                _poll(lambda: wrap.locator(chip_sel).count() == 0, timeout_ms=1500)
            before = wrap.locator(chip_sel).count()
            box = wrap.locator("input").first
            box.evaluate("e=>e.scrollIntoView({block:'center'})")
            box.evaluate("e => { e.focus(); e.click(); }")
            page.wait_for_timeout(200)
            page.keyboard.type(_keyword(value), delay=50)
            page.keyboard.press("Enter")
            _poll(lambda: page.locator(OPTION_SEL).count() > 0, timeout_ms=2000)
            page.wait_for_timeout(400)
            # find the best match instead of blindly picking the first
            picked = _best_field_match(page, value)
            if not picked:
                close_popups(page)
                if attempt < retries:
                    continue
                return False, f"no matching option for {value!r}"
            got_chip = _poll(
                lambda: wrap.locator(chip_sel).count() > before,
                timeout_ms=1500,
            )
            close_popups(page)
            if got_chip:
                sel = wrap.locator(chip_sel).last.inner_text().strip()
                return True, value if sel.lower() == value.lower() else f"{value} -> {sel}"
            if attempt < retries:
                continue
            return False, f"no option ~ {value!r}"
        except Exception as e:  # noqa: BLE001
            close_popups(page)
            if attempt < retries:
                continue
            return False, f"error: {e}"
    return False, f"failed after {retries + 1} attempts"


def fill_skills(page: Page, skills: list[str]):
    wrap = page.locator('[data-automation-id="formField-skills"]').first
    if not wrap.count():
        log("skills", False, "field missing")
        return
    chip_sel = '[data-automation-id="selectedItem"]'
    existing = [wrap.locator(chip_sel).nth(i).inner_text().strip().lower()
                for i in range(wrap.locator(chip_sel).count())]

    def _already_added(skill: str) -> bool:
        sl = skill.lower()
        for e in existing:
            if sl == e or sl == e.split("(")[0].strip() or e == sl:
                return True
            # "Python" matches "Python (Programming Language)"
            if f"{sl} " in e or f"{sl}(" in e:
                return True
        return False

    remaining = [s for s in skills if not _already_added(s)]
    if not remaining:
        log("skills", True, f"already set ({len(existing)} chips)")
        return
    box = wrap.locator("input").first
    box.evaluate("e=>e.scrollIntoView({block:'center'})")
    for s in remaining:
        try:
            close_popups(page)
            before = wrap.locator(chip_sel).count()
            box.evaluate("e => { e.focus(); e.click(); }")
            page.wait_for_timeout(150)
            page.keyboard.type(s, delay=40)
            page.keyboard.press("Enter")
            # Wait for initial options to appear
            _poll(
                lambda: (wrap.locator('[data-automation-id="promptOption"]').count() > 0
                         or wrap.locator('text="No Items."').count() > 0),
                timeout_ms=8000, interval_ms=500,
            )
            # Wait for dropdown to settle — results update dynamically
            page.wait_for_timeout(2000)

            no_items = wrap.locator('text="No Items."')
            # Options render globally, not inside the field wrapper
            options = page.locator('[data-automation-id="promptOption"]')
            vis_options = []
            for oi in range(options.count()):
                opt = options.nth(oi)
                try:
                    if opt.is_visible():
                        vis_options.append((opt, opt.inner_text().strip()))
                except Exception:
                    pass
            if no_items.count() and no_items.first.is_visible() and not vis_options:
                page.keyboard.press("Enter")
                page.wait_for_timeout(400)
            elif vis_options:
                clicked = False
                sl = s.lower()
                # Pass 1: exact match
                for opt, txt in vis_options:
                    if txt.lower() == sl:
                        _safe_click(opt)
                        clicked = True
                        break
                # Pass 2: skill name at start of option text
                if not clicked:
                    for opt, txt in vis_options:
                        if txt.lower().startswith(sl):
                            _safe_click(opt)
                            clicked = True
                            break
                # Pass 3: substring match
                if not clicked:
                    for opt, txt in vis_options:
                        if sl in txt.lower() or txt.lower() in sl:
                            _safe_click(opt)
                            clicked = True
                            break
                if not clicked:
                    log(f"skill: {s}", False, "no matching option")
                page.wait_for_timeout(400)
            else:
                page.keyboard.press("Enter")
                page.wait_for_timeout(400)

            # Clear search box for next skill
            box.fill("")
            page.wait_for_timeout(200)

            after = wrap.locator(chip_sel).count()
            if after > before:
                log(f"skill: {s}", True, "added")
            else:
                log(f"skill: {s}", False, "chip not added")
        except Exception as e:  # noqa: BLE001
            log(f"skill: {s}", False, f"error: {e}")
    close_popups(page)


def _find_websites_add(page: Page):
    """Find the Add button for the Websites section."""
    adds = page.locator('[data-automation-id="add-button"]')
    for i in range(adds.count()):
        btn = adds.nth(i)
        context = btn.evaluate(r'''el => {
            let p = el;
            for (let d = 0; d < 8 && p; d++) {
                const h = p.querySelector("h2, h3, h4, label, legend");
                if (h && h.innerText.trim()) return h.innerText.trim().toLowerCase();
                p = p.parentElement;
            }
            return "";
        }''')
        if "website" in context:
            return btn
    return None


def _text_nth_locator(page: Page, locator, value) -> tuple:
    """Fill a text input by locator directly (not by automation ID)."""
    el = locator.locator("input, textarea").first
    if not el.count():
        el = locator
    try:
        el.evaluate("e=>e.scrollIntoView({block:'center'})")
        el.click()
        el.fill(str(value))
        return True, "filled"
    except Exception as e:  # noqa: BLE001
        return False, f"error: {e}"


def _existing_urls(page: Page) -> set[str]:
    """Read all URL values already filled in website/link fields."""
    vals = set()
    for aid in ("formField-websiteAddress", "formField-websiteUrl",
                "formField-url", "formField-linkedInAccount"):
        fields = page.locator(f'[data-automation-id="{aid}"]')
        for i in range(fields.count()):
            inp = fields.nth(i).locator("input, textarea").first
            if inp.count():
                v = (inp.input_value() or "").strip()
                if v:
                    vals.add(v)
    return vals


def _count_website_panels(page: Page) -> int:
    return page.locator('[role="group"][aria-labelledby*="Websites"], '
                        '[role="group"][aria-labelledby*="website"]').count()


def fill_links(page: Page, links: dict):
    """Fill LinkedIn field if it exists, otherwise use the Websites section
    to add portfolio, LinkedIn, and GitHub links. Max 3 website entries total."""
    linkedin = links.get("linkedin", "")
    website = links.get("website", "")
    github = links.get("github", "")
    MAX_WEBSITES = 3

    # Try the dedicated LinkedIn field first
    li_field = page.locator('[data-automation-id="formField-linkedInAccount"]')
    if li_field.count() and linkedin:
        log("linkedin", *_text_nth(page, "formField-linkedInAccount", 0, linkedin))
        # Don't return — still fill website/github in the Websites section if present
        urls_to_add_after_li = [(u, "website" if u == website else "github")
                                for u in [website, github] if u]
        if not urls_to_add_after_li or not _section_present(page, "Websites"):
            return
        # Fall through to fill remaining links in Websites section

    # Check what's already filled to avoid duplicates
    already = _existing_urls(page)
    urls_to_add = [(u, "website" if u == website else ("linkedin" if u == linkedin else "github"))
                   for u in [website, linkedin, github] if u and u not in already]
    slots = MAX_WEBSITES - len(already)
    urls_to_add = urls_to_add[:max(slots, 0)]
    if not urls_to_add:
        if already:
            log("websites", True, f"already set ({len(already)} links)")
        return

    # Fill existing empty URL fields first before clicking Add
    url_fields = page.locator('[data-automation-id="formField-websiteAddress"]')
    if not url_fields.count():
        url_fields = page.locator('[data-automation-id="formField-websiteUrl"]')
    if not url_fields.count():
        url_fields = page.locator('[data-automation-id="formField-url"]')

    # Find empty slots among existing fields
    empty_indices = []
    for i in range(url_fields.count()):
        inp = url_fields.nth(i).locator("input, textarea").first
        if inp.count():
            val = (inp.input_value() or "").strip()
            if not val:
                empty_indices.append(i)

    filled = 0
    for url, label in urls_to_add:
        if empty_indices:
            idx = empty_indices.pop(0)
            log(f"link {label}", *_text_nth_locator(page, url_fields.nth(idx), url))
            filled += 1
            continue
        # Need to add a new block — but respect the cap
        if _count_website_panels(page) >= MAX_WEBSITES:
            log(f"link {label}", False, f"at {MAX_WEBSITES} website cap")
            break
        website_add = _find_websites_add(page)
        if not website_add:
            log(f"link {label}", False, "no Websites Add button")
            break
        website_add.scroll_into_view_if_needed()
        website_add.click()
        page.wait_for_timeout(600)
        # Re-query and fill the last (newest) field
        url_fields = page.locator('[data-automation-id="formField-websiteAddress"]')
        if not url_fields.count():
            url_fields = page.locator('[data-automation-id="formField-websiteUrl"]')
        if not url_fields.count():
            url_fields = page.locator('[data-automation-id="formField-url"]')
        if url_fields.count():
            idx = url_fields.count() - 1
            log(f"link {label}", *_text_nth_locator(page, url_fields.nth(idx), url))
            filled += 1
        else:
            log(f"link {label}", False, "URL input not found after Add")


def upload_resume(page: Page, path: str):
    fi = page.locator('input[type="file"]')
    if not fi.count():
        log("resume", False, "no file input on page")
        return
    # check if already uploaded
    already = (page.locator('[data-automation-id="file-upload-successful"]').count() > 0
               or page.get_by_text("Successfully Uploaded", exact=False).count() > 0
               or page.locator('[data-automation-id="file-upload-item"]').count() > 0)
    if already:
        log("resume", True, "already uploaded")
        return
    if not Path(path).exists():
        log("resume", False, f"file not found: {path}")
        return
    try:
        fi.first.set_input_files(path)
        uploaded = _poll(
            lambda: (page.locator('[data-automation-id="file-upload-successful"]').count() > 0
                     or page.get_by_text("Successfully Uploaded", exact=False).count() > 0),
            timeout_ms=8000,
        )
        log("resume", True, Path(path).name + (" (confirmed)" if uploaded else " (no confirmation)"))
    except Exception as e:  # noqa: BLE001
        log("resume", False, f"error: {e}")


def _verify_education(page: Page, schools: list[dict]):
    """Read back filled education values and fix any mismatches against profile."""
    profile_degrees = {
        "master": ["masters of science", "master of science", "ms", "m.s.",
                    "master's", "masters"],
        "bachelor": ["bachelor of science", "bachelors of science", "bs", "b.s.",
                      "bachelor's", "bachelors"],
    }
    for i, ed in enumerate(schools):
        level = _degree_level(str(ed.get("degree", "")))
        acceptable = profile_degrees.get(level, [])

        # Check degree
        deg_wrap = page.locator('[data-automation-id="formField-degree"]').nth(i)
        if deg_wrap.count():
            btn = deg_wrap.locator("button").first
            current = btn.inner_text().strip()
            cur_norm = current.lower().replace("'", "").replace("'", "")
            ok = any(a in cur_norm for a in acceptable) if acceptable else True
            if not ok and current != "Select One":
                console.print(f"[yellow]  edu[{i}] degree mismatch: got '{current}', fixing...[/yellow]")
                close_popups(page)
                btn.scroll_into_view_if_needed()
                btn.click()
                if widgets._wait_for_options(page):
                    picked = _pick_degree(page, str(ed.get("degree", "")))
                    close_popups(page)
                    if picked:
                        console.print(f"[green]  edu[{i}] degree fixed: {picked}[/green]")
                    else:
                        console.print(f"[red]  edu[{i}] degree: no match found[/red]")
                else:
                    close_popups(page)

        # Check field of study
        fos_wrap = page.locator('[data-automation-id="formField-fieldOfStudy"]').nth(i)
        if fos_wrap.count() and ed.get("field"):
            wanted = ed["field"]
            variants = FIELD_VARIANTS.get(wanted.lower(), [wanted])
            chip = fos_wrap.locator('[data-automation-id="selectedItem"]')
            if chip.count():
                current_fos = chip.first.inner_text().strip()
                ok_fos = any(current_fos.lower() == v.lower() for v in [wanted] + variants)
                if not ok_fos:
                    console.print(f"[yellow]  edu[{i}] field mismatch: got '{current_fos}', fixing...[/yellow]")
                    delete = chip.first.locator('[data-automation-id="DELETE_charm"]')
                    if delete.count():
                        delete.first.click()
                        page.wait_for_timeout(500)
                    ok, note = _multiselect_nth(page, "formField-fieldOfStudy", i, wanted)
                    if ok:
                        console.print(f"[green]  edu[{i}] field fixed: {note}[/green]")
                    else:
                        console.print(f"[red]  edu[{i}] field: {note}[/red]")

        # Check school
        school_aid = _school_aid(page)
        school_type = _school_widget_type(page, school_aid)
        school_wrap = page.locator(f'[data-automation-id="{school_aid}"]').nth(i)
        if school_wrap.count():
            if school_type == "multiselect":
                chip = school_wrap.locator('[data-automation-id="selectedItem"]')
                if chip.count():
                    current_school = chip.first.inner_text().strip()
                    expected = SCHOOL_PICK_NAMES.get(ed["school"].lower(), ed["school"])
                    if current_school.lower() != expected.lower():
                        console.print(f"[yellow]  edu[{i}] school mismatch: got '{current_school}', expected '{expected}'[/yellow]")
            else:
                inp = school_wrap.locator("input, textarea").first
                if inp.count():
                    current_school = (inp.input_value() or "").strip()
                    if current_school.lower() != ed["school"].lower():
                        console.print(f"[yellow]  edu[{i}] school mismatch: got '{current_school}'[/yellow]")


def _section_present(page: Page, heading: str) -> bool:
    """Check if a section exists on the page — either has fields or an Add button."""
    sel = f'h2:has-text("{heading}"), h3:has-text("{heading}"), h4:has-text("{heading}"), h5:has-text("{heading}")'
    return page.locator(sel).count() > 0


def fill_experience(page: Page, resume_path: str = "/Users/sambhav/projects/portfolio_v2/resume.pdf"):
    global results
    results = []
    p = load_profile()

    has_work = (page.locator('[data-automation-id="formField-jobTitle"]').count()
                or _section_present(page, "Work Experience")
                or _section_present(page, "Work History")
                or _section_present(page, "Work"))
    if has_work:
        fill_work(page, p["work_experience"])

    has_edu = (page.locator('[data-automation-id="formField-schoolName"]').count()
               or page.locator('[data-automation-id="formField-school"]').count()
               or _section_present(page, "Education"))
    if has_edu:
        fill_education(page, p["education"])
        _verify_education(page, p["education"])

    if page.locator('[data-automation-id="formField-skills"]').count():
        langs = p.get("skills", {}).get("languages", [])
        ml = p.get("skills", {}).get("ml_ai", [])
        # Expand "C/C++" into separate entries, deduplicate
        expanded = []
        seen_skills = set()
        for s in langs + ml:
            items = ["C++", "C"] if s == "C/C++" else [s]
            for item in items:
                if item.lower() not in seen_skills:
                    seen_skills.add(item.lower())
                    expanded.append(item)
        fill_skills(page, expanded[:12])

    fill_links(page, p.get("links", {}))
    upload_resume(page, resume_path)
    return results


def render():
    t = Table(title="My Experience — review (nothing submitted)")
    t.add_column("Field"); t.add_column("Result")
    for name, ok, note in results:
        mark = "[green]ok[/green]" if ok else "[red]NEEDS FIX[/red]"
        t.add_row(name, f"{mark}  [dim]{note}[/dim]")
    console.print(t)
    bad = [r for r in results if not r[1]]
    if bad:
        console.print(f"\n[yellow]{len(bad)} field(s) need attention.[/yellow]")
    console.print("\n[bold]Stopped before submit.[/bold] Review in Chrome.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--section", choices=["work", "education", "skills", "links", "resume", "all"], default="all")
    ap.add_argument("--resume", default="/Users/sambhav/projects/portfolio_v2/resume.pdf")
    args = ap.parse_args()
    p = load_profile()
    skills = (p.get("skills", {}).get("languages", []) + p.get("skills", {}).get("ml_ai", []))[:8]

    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_workday_tab(b)
        if not page:
            console.print("[red]No Workday tab open.[/red]")
            return
        if args.section in ("work", "all"):
            fill_work(page, p["work_experience"])
        if args.section in ("education", "all"):
            fill_education(page, p["education"])
        if args.section == "skills":
            fill_skills(page, skills)
        if args.section in ("links", "all"):
            fill_links(page, p.get("links", {}))
        if args.section in ("resume", "all"):
            upload_resume(page, args.resume)
        render()
        b.close()


if __name__ == "__main__":
    main()
