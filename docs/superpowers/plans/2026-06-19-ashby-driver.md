# Ashby Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Ashby (`jobs.ashbyhq.com`) driver behind the existing `ATSDriver` interface — single-page, label-based field matching, reusing the question engine, recorder, and a newly-shared captcha helper — so Ashby applications fill and (per config) submit through the unified `dispatch`.

**Architecture:** Extract `has_captcha`/`CAPTCHA_SEL` from `lever.py` into a shared `src/ats/captcha.py` (Lever refactored onto it). Add `src/ats/ashby.py` mirroring `lever.py`'s structure (pure helpers + browser fill + `apply_one` + `AshbyDriver`), with Ashby-specific label-based discovery. Register Ashby with one `detect_ats` line + one `_REGISTRY` line; no consumer changes.

**Tech Stack:** Python 3.14, Playwright (sync) over CDP, pytest, the existing `ApplyResult`/`ATSDriver` contract and `src/questions.py` engine.

## Global Constraints

- Python 3.14 + `playwright>=1.50`; use the project venv (`./venv/bin/python`, `./venv/bin/pytest`). Never global Python.
- Git: no `Co-Authored-By:` lines. Work stays on branch `feat/ashby-driver`.
- Sensitive answers (work-auth, sponsorship) come only from `profile.sensitive` via the question engine — never hardcoded/guessed.
- Captcha → never auto-submit; return `captcha` status (fill + stop), same as Lever.
- The only irreversible action is Submit; gate it behind the required-field brake (`missing_required` empty) + no-captcha.
- Reference Ashby DOM (live, Voleon Senior ML Eng, captured 2026-06-19): name `#_systemfield_name`, email `#_systemfield_email`, resume file input `#_systemfield_resume` (NOT the first `input[type=file]`, which is the "Autofill from resume" uploader); all other fields are per-job UUID `id`s with an associated `<label for="<id>">`; work-auth/sponsorship are single boolean checkboxes (check iff answer is "Yes"); submit is `button[type="submit"]` with text "Submit Application"; reCAPTCHA present (`textarea[name="g-recaptcha-response"]`).

---

### Task 1: Extract shared captcha helper

**Files:**
- Create: `src/ats/captcha.py`
- Modify: `src/ats/lever.py` (remove local `CAPTCHA_SEL`/`has_captcha`; import from `.captcha`)
- Test: `tests/test_ats_captcha.py`

**Interfaces:**
- Produces: `CAPTCHA_SEL: str`; `has_captcha(page) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ats_captcha.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats.captcha import CAPTCHA_SEL, has_captcha


class FakeLocator:
    def __init__(self, n): self._n = n
    def count(self): return self._n


class FakePage:
    def __init__(self, n): self._n = n
    def locator(self, sel):
        assert sel == CAPTCHA_SEL
        return FakeLocator(self._n)


def test_captcha_sel_covers_recaptcha_hcaptcha_turnstile():
    for token in ["hcaptcha", "recaptcha", "turnstile", "g-recaptcha-response"]:
        assert token in CAPTCHA_SEL


def test_has_captcha_true_when_present():
    assert has_captcha(FakePage(1)) is True


def test_has_captcha_false_when_absent():
    assert has_captcha(FakePage(0)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_ats_captcha.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ats.captcha'`

- [ ] **Step 3: Create `src/ats/captcha.py`**

```python
# src/ats/captcha.py
"""Shared captcha detection across ATS drivers. A present challenge means the
form cannot be auto-submitted — the human solves it and submits."""
from __future__ import annotations

CAPTCHA_SEL = ('#h-captcha, .h-captcha, iframe[src*="hcaptcha"], '
               '.g-recaptcha, iframe[src*="recaptcha"], '
               'iframe[src*="turnstile"], textarea[name="g-recaptcha-response"]')


def has_captcha(page) -> bool:
    """True if the page shows an hCaptcha/reCAPTCHA/Turnstile challenge."""
    return page.locator(CAPTCHA_SEL).count() > 0
```

- [ ] **Step 4: Refactor `src/ats/lever.py` onto the shared helper**

Delete the local definitions (currently near lines 173-179):

```python
CAPTCHA_SEL = ('#h-captcha, .h-captcha, iframe[src*="hcaptcha"], '
               '.g-recaptcha, iframe[src*="recaptcha"]')


def has_captcha(page) -> bool:
    """True if the form shows an hCaptcha/reCAPTCHA challenge — submission needs a human."""
    return page.locator(CAPTCHA_SEL).count() > 0
```

Add an import near the top of `lever.py`, beside the other `from .` imports (e.g. after `from .base import ApplyResult`):

```python
from .captcha import has_captcha
```

`lever.py` calls only `has_captcha(page)` (the local `CAPTCHA_SEL` had no other references), so no other lever code changes.

- [ ] **Step 5: Run tests**

Run: `./venv/bin/pytest tests/test_ats_captcha.py -v` → Expected: PASS (3 passed)
Run: `./venv/bin/pytest -q` → Expected: all pass (Lever's behavior unchanged; the new `CAPTCHA_SEL` is a superset of its old one).

- [ ] **Step 6: Commit**

```bash
git add src/ats/captcha.py src/ats/lever.py tests/test_ats_captcha.py
git commit -m "refactor(ats): extract shared captcha helper; lever uses it (#2)"
```

---

### Task 2: Ashby pure helpers — `ashby_job_meta`, `ashby_field_value`

**Files:**
- Create: `src/ats/ashby.py`
- Test: `tests/test_ashby_helpers.py`

**Interfaces:**
- Consumes: `full_name`, `current_company` from `src/ats/lever.py` (existing pure helpers).
- Produces:
  - `ashby_job_meta(url: str) -> dict` — `{company, tenant, job_id}` from `jobs.ashbyhq.com/<company>/<job-id>[/application]`.
  - `ashby_field_value(label: str, profile: dict) -> str | None` — value for a known contact/link field by label, else None.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ashby_helpers.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats import ashby

PROFILE = {
    "identity": {"first_name": "Sambhav", "last_name": "Shrestha",
                 "email": "sambhavshrestha111@gmail.com", "phone": "9293196443"},
    "contact": {"city": "Port Jefferson", "state": "NY"},
    "links": {"linkedin": "https://www.linkedin.com/in/sambhav101",
              "website": "https://sambhavshrestha.com",
              "github": "https://www.github.com/sambhav101"},
    "work_experience": [{"company": "HCL Technologies", "end": "2025-07", "current": False}],
}


def test_job_meta_with_application_suffix():
    m = ashby.ashby_job_meta("https://jobs.ashbyhq.com/voleon/e5c0863d-1371-4790-a50f-b467fa544b08/application")
    assert m["company"] == "voleon"
    assert m["tenant"] == "voleon"
    assert m["job_id"] == "e5c0863d-1371-4790-a50f-b467fa544b08"


def test_job_meta_without_suffix():
    m = ashby.ashby_job_meta("https://jobs.ashbyhq.com/openai/4a13c764")
    assert m["company"] == "openai"
    assert m["job_id"] == "4a13c764"


def test_field_value_known_labels():
    assert ashby.ashby_field_value("Email", PROFILE) == "sambhavshrestha111@gmail.com"
    assert ashby.ashby_field_value("Phone Number", PROFILE) == "9293196443"
    assert ashby.ashby_field_value("Current Company", PROFILE) == "HCL Technologies"
    assert ashby.ashby_field_value("Current Location", PROFILE) == "Port Jefferson, NY"
    assert ashby.ashby_field_value("LinkedIn", PROFILE) == "https://www.linkedin.com/in/sambhav101"
    assert ashby.ashby_field_value("GitHub", PROFILE) == "https://www.github.com/sambhav101"
    assert ashby.ashby_field_value("Portfolio", PROFILE) == "https://sambhavshrestha.com"
    assert ashby.ashby_field_value("Full Name", PROFILE) == "Sambhav Shrestha"


def test_field_value_unknown_label_returns_none():
    assert ashby.ashby_field_value("What is your favorite color?", PROFILE) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_ashby_helpers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ats.ashby'`

- [ ] **Step 3: Create `src/ats/ashby.py` with the pure helpers**

```python
# src/ats/ashby.py
"""Ashby ATS driver (jobs.ashbyhq.com). Single-page React form, no account,
captcha-gated. Mirrors lever.py; behind the shared ATSDriver interface.

    ./venv/bin/python -m src.ats.ashby <url>                 # fill, submit per config
    ./venv/bin/python -m src.ats.ashby --no-submit <url>     # fill only, stop
"""
from __future__ import annotations

from urllib.parse import urlparse

from .base import ApplyResult
from .captcha import has_captcha
from .lever import full_name, current_company, _notify
from ..questions import _answer_for, _sensitive_answer, FLAG


def ashby_job_meta(url: str) -> dict:
    """Derive company/tenant/job_id from jobs.ashbyhq.com/<company>/<job-id>[/application]."""
    parts = [p for p in urlparse(url).path.split("/") if p and p != "application"]
    company = parts[0] if parts else ""
    job_id = parts[1] if len(parts) >= 2 else ""
    return {"company": company, "tenant": company, "job_id": job_id}


def ashby_field_value(label: str, profile: dict) -> str | None:
    """Value for a known Ashby contact/link field, matched by label. None if unknown."""
    l = label.lower()
    ident = profile.get("identity", {})
    links = profile.get("links", {})
    contact = profile.get("contact", {})
    if "full name" in l or l == "name":
        return full_name(profile)
    if "email" in l:
        return ident.get("email", "")
    if "phone" in l:
        return str(ident.get("phone", "")) or None
    if "current company" in l or l == "company":
        return current_company(profile) or None
    if "location" in l:
        loc = ", ".join(p for p in (contact.get("city", ""), contact.get("state", "")) if p)
        return loc or None
    if "linkedin" in l:
        return links.get("linkedin", "") or None
    if "github" in l:
        return links.get("github", "") or None
    if "portfolio" in l or "website" in l:
        return links.get("website", "") or None
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_ashby_helpers.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ats/ashby.py tests/test_ashby_helpers.py
git commit -m "feat(ashby): job-meta + label→value pure helpers (#2)"
```

---

### Task 3: Ashby browser fill, driver, registration

**Files:**
- Modify: `src/ats/ashby.py` (add browser functions + `AshbyDriver` + `main`)
- Modify: `src/ats/__init__.py` (`detect_ats` + `_REGISTRY`)
- Test: `tests/test_ats_dispatch.py` (extend — Ashby routing)
- Test: live (browser), per Step 8

**Interfaces:**
- Consumes: `ashby_job_meta`, `ashby_field_value` (Task 2); `has_captcha` (Task 1); `ApplyResult` (`base`); `_sensitive_answer`/`_answer_for`/`FLAG` (`questions`); `dispatch`/`driver_for` (`src/ats/__init__.py`).
- Produces: `fill_application(page, profile) -> list[str]`, `missing_required(page) -> list[str]`, `submit(page) -> None`, `apply_one(url=None, *, auto_submit=False, page=None) -> dict`, `class AshbyDriver` (`name="ashby"`), `main()`. `detect_ats` returns `"ashby"` for `jobs.ashbyhq.com`; `_REGISTRY["ashby"]` set.

- [ ] **Step 1: Write the failing routing test**

```python
# append to tests/test_ats_dispatch.py
def test_driver_for_maps_ashby():
    from src.ats.ashby import AshbyDriver
    assert isinstance(driver_for("https://jobs.ashbyhq.com/voleon/abc/application"), AshbyDriver)


def test_dispatch_routes_to_ashby(monkeypatch):
    import src.ats.ashby as ashby_mod
    monkeypatch.setattr(ashby_mod, "apply_one",
                        lambda url=None, *, auto_submit=False, page=None:
                        {"status": "captcha", "reason": "solve it", "company": "voleon"})
    r = dispatch(FakePage(), "https://jobs.ashbyhq.com/voleon/abc/application", auto_submit=True)
    assert r.status is ApplyStatus.CAPTCHA
    assert r.job["company"] == "voleon"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/pytest tests/test_ats_dispatch.py::test_driver_for_maps_ashby -v`
Expected: FAIL — `driver_for(...ashby...)` returns None (Ashby not registered yet).

- [ ] **Step 3: Add the browser functions to `src/ats/ashby.py`**

```python
SUBMIT_BTN = 'button[type="submit"]:has-text("Submit Application")'
_SYSTEM_IDS = {"_systemfield_name", "_systemfield_email", "_systemfield_resume"}

_LABEL_PAIRS_JS = """() => [...document.querySelectorAll('label[for]')]
    .map(l => ({id: l.getAttribute('for'), label: (l.innerText || '').trim()}))
    .filter(p => p.id && p.label)"""


def _fill_by_selector(page, selector: str, value: str) -> None:
    loc = page.locator(selector)
    if loc.count() and value:
        loc.first.fill(value)


def _is_required(el) -> bool:
    return el.get_attribute("required") is not None or el.get_attribute("aria-required") == "true"


def fill_application(page, profile: dict) -> list[str]:
    flags: list[str] = []

    # 1. Stable system fields
    _fill_by_selector(page, '#_systemfield_name', full_name(profile))
    _fill_by_selector(page, '#_systemfield_email', profile.get("identity", {}).get("email", ""))

    # 2. Resume → the system resume input specifically (NOT the autofill uploader)
    resume_path = profile.get("resume_path", "")
    resume = page.locator('#_systemfield_resume')
    if resume_path and resume.count():
        resume.first.set_input_files(resume_path)

    # 3. Custom fields by label (label[for] ↔ input id)
    for pair in page.evaluate(_LABEL_PAIRS_JS):
        fid, label = pair["id"], pair["label"]
        if fid in _SYSTEM_IDS:
            continue
        loc = page.locator(f'[id="{fid}"]')
        if not loc.count():
            continue
        el = loc.first
        kind = (el.get_attribute("type") or el.evaluate("e => e.tagName.toLowerCase()")).lower()

        if kind == "checkbox":
            # boolean checkbox (work-auth/sponsorship): check iff the answer is "Yes"
            ans = _sensitive_answer(label, profile)
            if ans is None:
                ans = _answer_for(label)
            if ans is FLAG or ans is None:
                if _is_required(el):
                    flags.append(f"{label!r}: needs manual answer")
                continue
            if ans == "Yes":
                # JS click dispatches directly on the input (React-/overlay-safe)
                el.evaluate("e => { if (!e.checked) e.click(); }")
            continue

        # text / tel / email / textarea
        value = ashby_field_value(label, profile)
        if value is None:
            rule = _answer_for(label)
            value = rule if isinstance(rule, str) else None
        if value:
            el.fill(value)
        elif _is_required(el):
            flags.append(f"{label!r}: needs manual answer")
    return flags


def missing_required(page) -> list[str]:
    """Labels of required fields still empty (text/textarea blank, or file with no upload)."""
    missing: list[str] = []
    req = page.locator('input[required], input[aria-required="true"], '
                       'textarea[required], textarea[aria-required="true"]')
    for i in range(req.count()):
        el = req.nth(i)
        fid = el.get_attribute("id") or ""
        label = ""
        if fid:
            lab = page.locator(f'label[for="{fid}"]')
            if lab.count():
                label = lab.first.inner_text().strip()
        label = label or fid or "unknown"
        if (el.get_attribute("type") or "").lower() == "file":
            if not el.evaluate("e => !!(e.files && e.files.length)"):
                missing.append(label)
            continue
        if not (el.input_value() or "").strip():
            missing.append(label)
    return missing


def submit(page) -> None:
    btn = page.locator(SUBMIT_BTN)
    btn.first.scroll_into_view_if_needed()
    btn.first.click()
    page.wait_for_timeout(4000)
```

- [ ] **Step 4: Add `apply_one`, `AshbyDriver`, and `main` to `src/ats/ashby.py`**

```python
def apply_one(url: str | None = None, *, auto_submit: bool = False, page=None) -> dict:
    from .. import browser
    from ..profile import load_profile
    from ..record import parse_job, stash_job, _load, _save
    from playwright.sync_api import sync_playwright
    import datetime

    own_browser = page is None
    pw = b = None
    if own_browser:
        pw = sync_playwright().start()
        b = browser.connect(pw)
        page = browser.find_any_tab(b)

    def _finish(result: dict) -> dict:
        if own_browser and b:
            b.close()
            pw.stop()
        return result

    try:
        if url:
            target = url if url.rstrip("/").endswith("/application") else url.rstrip("/") + "/application"
            page.goto(target)
            page.wait_for_timeout(3000)
        profile = load_profile()
        job = parse_job(page.url, page)
        job.update(ashby_job_meta(page.url))
        job["url"] = page.url.split("?")[0]

        flags = fill_application(page, profile)
        missing = missing_required(page)
        if flags or missing:
            reason = f"Unanswered required fields — missing: {missing}; flagged: {flags}"
            return _finish({"status": "blocked", "reason": reason, **job})

        if has_captcha(page):
            return _finish({"status": "captcha",
                            "reason": "Form filled. CAPTCHA present — solve it in the "
                                      "browser and click Submit yourself.", **job})

        if not auto_submit:
            return _finish({"status": "review", "reason": "Filled; stopped before submit", **job})

        stash_job(job, url=job["url"])
        submit(page)
        entry = {**job, "status": "Submitted",
                 "submitted_at": datetime.date.today().isoformat()}
        entries = [e for e in _load()
                   if (e.get("tenant"), e.get("job_id")) != (entry.get("tenant"), entry.get("job_id"))
                   or not entry.get("job_id")]
        entries.append(entry)
        _save(entries)
        return _finish({"status": "submitted", "reason": "Submitted and recorded", **job})
    except Exception as e:  # noqa: BLE001
        return _finish({"status": "error", "reason": str(e), "url": url or ""})


class AshbyDriver:
    name = "ashby"

    def apply(self, page, url: str, *, auto_submit: bool) -> ApplyResult:
        return ApplyResult.from_dict(apply_one(url, auto_submit=auto_submit, page=page))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="Ashby job URL")
    ap.add_argument("--no-submit", action="store_true",
                    help="fill only and stop before Submit (overrides auto_submit)")
    args = ap.parse_args()

    import yaml
    from pathlib import Path
    cfg_path = Path(__file__).resolve().parent.parent.parent / "agent_config.yaml"
    auto = False
    if cfg_path.exists():
        auto = bool(yaml.safe_load(cfg_path.read_text()).get("auto_submit", False))
    if args.no_submit:
        auto = False

    result = apply_one(args.url, auto_submit=auto)
    print(result["status"].upper(), "-", result["reason"])
    if result["status"] == "captcha":
        _notify("Ashby: CAPTCHA — action needed",
                f"{result.get('company', 'job')} filled. Solve the captcha and submit.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Register Ashby in `src/ats/__init__.py`**

In `detect_ats`, add before the final `return "unknown"`:

```python
    if "jobs.ashbyhq.com" in host:
        return "ashby"
```

Add the import beside the other driver imports and the registry entry:

```python
from .ashby import AshbyDriver
```
```python
_REGISTRY: dict[str, ATSDriver] = {
    "workday": WorkdayDriver(),
    "lever": LeverDriver(),
    "ashby": AshbyDriver(),
}
```

- [ ] **Step 6: Run the routing tests + full suite**

Run: `./venv/bin/pytest tests/test_ats_dispatch.py -v` → Expected: PASS (Ashby routing tests included)
Run: `./venv/bin/python -c "import src.ats.ashby, src.ats; print('import ok')"` → Expected: `import ok` (no import cycle)
Run: `./venv/bin/pytest -q` → Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/ats/ashby.py src/ats/__init__.py tests/test_ats_dispatch.py
git commit -m "feat(ashby): browser fill, driver, registration (#2)"
```

- [ ] **Step 8: Live verification (manual — needs Chrome on CDP; performed by the controller)**

Launch Chrome (`scripts/launch_chrome.sh`), ensure `resume_path` is set in `profile.yaml`, then:

```bash
./venv/bin/python -m src.ats.ashby --no-submit "https://jobs.ashbyhq.com/voleon/e5c0863d-1371-4790-a50f-b467fa544b08/application"
```

Expected: prints `CAPTCHA - Form filled...` (the form has reCAPTCHA). In the browser confirm: Full Name / Email filled, resume attached to the **Resume** field (not "Autofill from resume"), Phone / Current Company / LinkedIn / GitHub / Portfolio filled, work-auth checkbox state matches `profile.sensitive`. Watch the two flagged risks: React `.fill()` values must persist (if any revert, fall back to `.type()` / native-setter+`input` dispatch), and the work-auth checkbox must toggle. Fix any live issues, then re-commit.

---

## Self-Review

**Spec coverage:**
- Shared `captcha.py` + Lever refactored onto it → Task 1. ✓
- `src/ats/ashby.py` mirroring Lever, behind the interface → Tasks 2-3. ✓
- Stable name/email/resume selectors; resume `#_systemfield_resume` (avoid autofill uploader) → Task 3 `fill_application`. ✓
- Label-based matching for everything else; work-auth/sponsorship from `profile.sensitive` via the question engine → Task 3. ✓
- `ashby_job_meta` URL parsing → Task 2. ✓
- Captcha → `captcha` status (never auto-submit) → Task 3 `apply_one`. ✓
- Required-field brake → Task 3 `missing_required`. ✓
- Registration (one `detect_ats` line + one `_REGISTRY` line; no consumer changes) → Task 3. ✓
- Testing: offline units (Tasks 1-3) + live (Task 3 Step 8). ✓
- Risks (React fill, work-auth widget) flagged for live confirmation → Task 3 Step 8. ✓
- Out of scope (broader form-fill helper, Greenhouse, web UI styling) → none added. ✓

**Placeholder scan:** No TBD/TODO; every code step is complete. The React-fill fallback is an explicit live-verification instruction, not a code placeholder. ✓

**Type consistency:** `ashby_job_meta`/`ashby_field_value`/`fill_application`/`missing_required`/`submit`/`apply_one`/`AshbyDriver` names and signatures match across Tasks 2-3; `apply_one` returns the same `{status, reason, **job}` dict shape Lever/Workday use; `AshbyDriver.apply` returns `ApplyResult` via `from_dict`; reuses `full_name`/`current_company`/`_notify` from `lever.py` and `_sensitive_answer`/`_answer_for`/`FLAG` from `questions.py`. ✓

**Noted coupling (intentional, to relocate at Greenhouse-extraction time):** `ashby.py` imports `full_name`/`current_company`/`_notify` from `lever.py` (pure reuse, no duplication/drift). When the 3rd single-page ATS lands, these move to the shared module alongside the form-fill helper.
