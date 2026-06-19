# Lever ATS Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `src/ats/lever.py` so `python -m src.ats.lever <url>` fills and (per config) auto-submits a Lever job application from `profile.yaml`, reusing the existing question engine, browser connection, profile loader, and resume uploader.

**Architecture:** A standalone Lever driver (deliberately NOT behind an interface yet — that extraction is the next phase). Pure mapping/answering functions are unit-tested without a browser; browser I/O is verified manually against the live Hive posting. A tiny `detect_ats(url)` router wires Lever into the existing agent dispatch.

**Tech Stack:** Python 3.14, Playwright (sync API) over CDP to a real Chrome, pytest, PyYAML.

## Global Constraints

- Python runs on 3.14 with `playwright>=1.50`; use the project venv at `./venv` (`./venv/bin/python`, `./venv/bin/pytest`). Never install into global Python.
- Sensitive fields (work auth, sponsorship, EEO) are read from `profile.yaml` only — never LLM-guessed or hardcoded.
- The only irreversible action is Submit. Auto-submit MUST be gated by a pre-submit required-field check; if any required field is unanswered, refuse to submit.
- Honor `agent_config.yaml: auto_submit` and a `--no-submit` CLI flag.
- Git: no `Co-Authored-By:` lines in commits. Work stays on branch `feat/lever-ats`.
- Reference Lever DOM (live, captured 2026-06-19, Hive ML Engineer): standard inputs by `name` (`name`, `email`, `phone`, `location`, `org`, `urls[LinkedIn]`, `urls[Twitter]`, `urls[GitHub]`, `urls[Portfolio]`, `urls[Other]`); resume `input[type=file][name=resume]`; custom questions `cards[<uuid>][fieldN]` matched by label text; submit button `button.template-btn-submit` (text "SUBMIT APPLICATION").

---

### Task 1: Package scaffold + ATS detection

**Files:**
- Create: `src/ats/__init__.py`
- Test: `tests/test_ats_detect.py`

**Interfaces:**
- Produces: `detect_ats(url: str) -> str` returning `"workday"`, `"lever"`, or `"unknown"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ats_detect.py
from src.ats import detect_ats


def test_detects_lever():
    assert detect_ats("https://jobs.lever.co/hive/abc-123/apply") == "lever"


def test_detects_workday():
    assert detect_ats("https://adobe.wd5.myworkdayjobs.com/en-US/job/x") == "workday"


def test_unknown_host():
    assert detect_ats("https://boards.greenhouse.io/foo/jobs/1") == "unknown"


def test_garbage_url():
    assert detect_ats("not a url") == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_ats_detect.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ats'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ats/__init__.py
"""ATS routing for the autofill pipeline. Spike-level: a host check only."""
from __future__ import annotations

from urllib.parse import urlparse


def detect_ats(url: str) -> str:
    """Identify the ATS provider from a job URL. Returns 'workday', 'lever', or 'unknown'."""
    host = (urlparse(url).hostname or "").lower()
    if "myworkdayjobs.com" in host:
        return "workday"
    if "jobs.lever.co" in host:
        return "lever"
    return "unknown"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_ats_detect.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ats/__init__.py tests/test_ats_detect.py
git commit -m "feat(ats): package scaffold + detect_ats router (#2)"
```

---

### Task 2: Standard field mapping (pure)

**Files:**
- Create: `src/ats/lever.py`
- Test: `tests/test_lever_mapping.py`

**Interfaces:**
- Consumes: a profile dict shaped like `profile.yaml` (`identity`, `contact`, `links`, `work_experience`, `education`, `sensitive`, `preferences`, `resume_path`).
- Produces:
  - `full_name(profile: dict) -> str`
  - `current_company(profile: dict) -> str`
  - `standard_field_values(profile: dict) -> dict[str, str]` — maps Lever standard input `name` → value, omitting any value that is empty.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lever_mapping.py
from src.ats import lever

PROFILE = {
    "identity": {"first_name": "Sambhav", "last_name": "Shrestha",
                 "email": "sambhavshrestha111@gmail.com", "phone": "9293196443"},
    "contact": {"city": "Port Jefferson", "state": "NY"},
    "links": {"linkedin": "https://www.linkedin.com/in/sambhav101",
              "website": "https://sambhavshrestha.com",
              "github": "https://www.github.com/sambhav101"},
    "work_experience": [
        {"company": "HCL Technologies", "end": "2025-07", "current": False},
        {"company": "Amazon", "end": "2023-03", "current": False},
    ],
}


def test_full_name():
    assert lever.full_name(PROFILE) == "Sambhav Shrestha"


def test_current_company_picks_latest_end():
    assert lever.current_company(PROFILE) == "HCL Technologies"


def test_standard_field_values():
    vals = lever.standard_field_values(PROFILE)
    assert vals["name"] == "Sambhav Shrestha"
    assert vals["email"] == "sambhavshrestha111@gmail.com"
    assert vals["phone"] == "9293196443"
    assert vals["location"] == "Port Jefferson, NY"
    assert vals["org"] == "HCL Technologies"
    assert vals["urls[LinkedIn]"] == "https://www.linkedin.com/in/sambhav101"
    assert vals["urls[GitHub]"] == "https://www.github.com/sambhav101"
    assert vals["urls[Portfolio]"] == "https://sambhavshrestha.com"


def test_standard_field_values_omits_empty():
    vals = lever.standard_field_values({"identity": {"first_name": "A", "last_name": "B"}})
    assert "email" not in vals
    assert "urls[LinkedIn]" not in vals
    assert vals["name"] == "A B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_lever_mapping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ats.lever'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ats/lever.py
"""Lever ATS driver (spike). Single-page form: fill from profile.yaml, then
optionally auto-submit. Standalone — not behind an ATSDriver interface yet.

    ./venv/bin/python -m src.ats.lever <url>                 # fill, then submit per config
    ./venv/bin/python -m src.ats.lever --no-submit <url>     # fill only, stop before submit
"""
from __future__ import annotations


def full_name(profile: dict) -> str:
    ident = profile.get("identity", {})
    parts = [ident.get("first_name", ""), ident.get("last_name", "")]
    return " ".join(p for p in parts if p).strip()


def current_company(profile: dict) -> str:
    """Most relevant employer: the one flagged current, else the latest-ending job."""
    jobs = profile.get("work_experience") or []
    if not jobs:
        return ""
    current = next((j for j in jobs if j.get("current")), None)
    if current is None:
        with_end = [j for j in jobs if str(j.get("end", "")).strip()]
        current = max(with_end, key=lambda j: str(j["end"]), default=jobs[0])
    return current.get("company", "")


def standard_field_values(profile: dict) -> dict[str, str]:
    """Map profile -> Lever standard input `name` -> value. Omits empty values."""
    ident = profile.get("identity", {})
    contact = profile.get("contact", {})
    links = profile.get("links", {})

    city, state = contact.get("city", ""), contact.get("state", "")
    location = ", ".join(p for p in (city, state) if p)

    raw = {
        "name": full_name(profile),
        "email": ident.get("email", ""),
        "phone": str(ident.get("phone", "")),
        "location": location,
        "org": current_company(profile),
        "urls[LinkedIn]": links.get("linkedin", ""),
        "urls[GitHub]": links.get("github", ""),
        "urls[Portfolio]": links.get("website", ""),
    }
    return {k: v for k, v in raw.items() if v}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_lever_mapping.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ats/lever.py tests/test_lever_mapping.py
git commit -m "feat(lever): standard field mapping from profile (#2)"
```

---

### Task 3: Custom question answering (pure)

**Files:**
- Modify: `src/ats/lever.py` (add functions)
- Test: `tests/test_lever_questions.py`

**Interfaces:**
- Consumes: `from ..questions import _answer_for, _sensitive_answer, FLAG` (existing; `_sensitive_answer` returns a `"Yes"`/`"No"` string, the `FLAG` sentinel when sensitive-but-unanswered, or `None` when not a sensitive question).
- Produces:
  - `gpa(profile: dict) -> str` — GPA of the current (else latest-ending) education entry, `""` if none.
  - `answer_custom(label: str, profile: dict) -> str | object | None` — answer for a custom question label. Returns a string to type, the `FLAG` sentinel (must be answered by a human), or `None` (unknown → treat as flag).
  - `choose_checkbox(question_label: str, option_labels: list[str], profile: dict) -> str | None` — which checkbox option to tick for a multi-select question, matched from `preferences.how_did_you_hear`; `None` if no confident match.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lever_questions.py
from src.ats import lever
from src.questions import FLAG

PROFILE = {
    "education": [
        {"school": "Stony Brook", "gpa": "3.5", "end": "2027-06", "current": True},
        {"school": "St. Joseph's", "gpa": "3.93", "end": "2022-06", "current": False},
    ],
    "sensitive": {"requires_sponsorship": "No", "work_authorization": "Yes"},
    "preferences": {"how_did_you_hear": "Job Board > LinkedIn"},
}


def test_gpa_uses_current_education():
    assert lever.gpa(PROFILE) == "3.5"


def test_answer_custom_gpa():
    assert lever.answer_custom("What is/was your GPA?", PROFILE) == "3.5"


def test_answer_custom_sponsorship_from_profile():
    ans = lever.answer_custom(
        "Will you now or in the future require sponsorship for employment?", PROFILE)
    assert ans == "No"


def test_answer_custom_sensitive_unanswered_flags():
    ans = lever.answer_custom("Will you require sponsorship?", {"sensitive": {}})
    assert ans is FLAG


def test_answer_custom_unknown_returns_none():
    assert lever.answer_custom("What is your favorite color?", PROFILE) is None


def test_choose_checkbox_matches_how_did_you_hear():
    options = ["Friend", "Recruiter/current employee", "LinkedIn", "AngelList", "Other"]
    assert lever.choose_checkbox("How did you hear about us?", options, PROFILE) == "LinkedIn"


def test_choose_checkbox_no_match_returns_none():
    options = ["Friend", "Recruiter/current employee"]
    assert lever.choose_checkbox("How did you hear about us?", options, PROFILE) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_lever_questions.py -v`
Expected: FAIL with `AttributeError: module 'src.ats.lever' has no attribute 'gpa'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/ats/lever.py` (after the imports line `from __future__ import annotations`, add the import; append the functions):

```python
from ..questions import _answer_for, _sensitive_answer, FLAG


def gpa(profile: dict) -> str:
    eds = profile.get("education") or []
    chosen = next((e for e in eds if e.get("current")), None)
    if chosen is None:
        with_end = [e for e in eds if str(e.get("end", "")).strip()]
        chosen = max(with_end, key=lambda e: str(e["end"]), default=None)
    return str(chosen.get("gpa", "")) if chosen else ""


def answer_custom(label: str, profile: dict):
    """Answer a custom Lever question by label. Returns a string, FLAG, or None."""
    q = label.lower()
    if "gpa" in q:
        return gpa(profile) or FLAG
    sens = _sensitive_answer(label, profile)
    if sens is not None:
        return sens  # "Yes"/"No" or FLAG
    rule = _answer_for(label)
    if rule is not None:
        return rule
    return None


def choose_checkbox(question_label: str, option_labels: list[str], profile: dict):
    """Pick a checkbox option from preferences.how_did_you_hear (last path segment)."""
    pref = profile.get("preferences", {}).get("how_did_you_hear", "")
    target = pref.split(">")[-1].strip().lower()
    if not target:
        return None
    for opt in option_labels:
        if opt.strip().lower() == target:
            return opt
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_lever_questions.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ats/lever.py tests/test_lever_questions.py
git commit -m "feat(lever): custom question answering via existing engine (#2)"
```

---

### Task 4: Browser fill (standard fields + custom questions + resume)

**Files:**
- Modify: `src/ats/lever.py` (add browser functions)
- Test: manual (browser I/O against live Lever; no pytest)

**Interfaces:**
- Consumes: `from ..experience import upload_resume` (existing: `upload_resume(page, path)` finds `input[type=file]` and calls `set_input_files`); `from playwright.sync_api import Page`.
- Produces:
  - `fill_application(page: "Page", profile: dict) -> list[str]` — fills every field it can; returns a list of human-readable flags for questions it could not answer.

- [ ] **Step 1: Write the implementation**

Add to `src/ats/lever.py`:

```python
def _fill_text_by_name(page, name: str, value: str) -> bool:
    loc = page.locator(f'[name="{name}"]')
    if not loc.count():
        return False
    loc.first.fill(value)
    return True


def _custom_cards(page):
    """Yield (card_li, label_text, kind, inputs_locator) for each custom question.
    kind is 'text', 'textarea', or 'checkbox'."""
    cards = page.locator('li[class*="application-question"], ul.application-additional li')
    results = []
    for i in range(cards.count()):
        li = cards.nth(i)
        label = (li.locator('.application-label, label').first.inner_text()
                 if li.locator('.application-label, label').count() else "").strip()
        if not label:
            continue
        if li.locator('input[type="checkbox"]').count():
            results.append((li, label, "checkbox"))
        elif li.locator('textarea').count():
            results.append((li, label, "textarea"))
        elif li.locator('input[type="text"]').count():
            results.append((li, label, "text"))
    return results


def fill_application(page, profile: dict) -> list[str]:
    flags: list[str] = []

    # 1. Standard fields by stable name
    for name, value in standard_field_values(profile).items():
        _fill_text_by_name(page, name, value)

    # 2. Resume upload (reuses Workday uploader; same input[type=file] pattern)
    upload_resume(page, profile.get("resume_path", ""))

    # 3. Custom questions by label
    for li, label, kind in _custom_cards(page):
        if kind == "checkbox":
            opts = li.locator('input[type="checkbox"]')
            opt_labels = [li.locator('input[type="checkbox"]').nth(j)
                          .locator('xpath=following-sibling::*[1]').inner_text().strip()
                          for j in range(opts.count())]
            pick = choose_checkbox(label, opt_labels, profile)
            if pick is None:
                flags.append(f"{label!r}: no checkbox match")
                continue
            idx = opt_labels.index(pick)
            opts.nth(idx).check()
        else:
            ans = answer_custom(label, profile)
            if ans is FLAG or ans is None:
                flags.append(f"{label!r}: needs manual answer")
                continue
            sel = 'textarea' if kind == "textarea" else 'input[type="text"]'
            li.locator(sel).first.fill(str(ans))
    return flags
```

- [ ] **Step 2: Manual verification against the live form**

Ensure Chrome is running on CDP (see README `scripts/launch_chrome.sh`) and `resume_path` is set in `profile.yaml`. Then run a throwaway REPL:

```bash
./venv/bin/python -c "
from playwright.sync_api import sync_playwright
from src import browser
from src.profile import load_profile
from src.ats import lever
with sync_playwright() as pw:
    b = browser.connect(pw)
    page = browser.find_any_tab(b)
    page.goto('https://jobs.lever.co/hive/fb175ecc-b6ba-4242-a84a-8699f9b0e971/apply')
    page.wait_for_timeout(3000)
    print('FLAGS:', lever.fill_application(page, load_profile()))
    b.close()
"
```

Expected: in the browser, Full name / Email / Phone / Current location / Current company / LinkedIn / GitHub / Portfolio are filled, the resume is attached, GPA shows `3.5`, the sponsorship textarea shows `No`, and the "LinkedIn" checkbox under "How did you hear" is ticked. `FLAGS: []` printed (no manual-answer flags). Do NOT submit yet.

- [ ] **Step 3: Commit**

```bash
git add src/ats/lever.py
git commit -m "feat(lever): fill standard fields, custom questions, resume (#2)"
```

---

### Task 5: Required-field check, submit, safety brake, CLI

**Files:**
- Modify: `src/ats/lever.py` (add verification, submit, `apply_one`, `main`)
- Test: manual (browser)

**Interfaces:**
- Consumes: `from .. import browser`; `from ..profile import load_profile`; `from ..record import stash_job, parse_job, _load, _save`; `from playwright.sync_api import sync_playwright`; `import datetime, argparse, yaml`.
- Produces:
  - `missing_required(page) -> list[str]` — labels of required (`✱`) fields still empty.
  - `submit(page) -> None` — clicks the Lever submit button.
  - `apply_one(url: str | None = None, *, auto_submit: bool = False, page=None) -> dict` — full flow for one Lever job; returns `{"status": ..., "reason": ..., **job_meta}` matching `apply.py`'s result shape (`status` in `submitted`/`review`/`blocked`/`error`). When `page` is provided it is reused (no browser open/close); otherwise a browser is opened and closed.

- [ ] **Step 1: Write the implementation**

Add to `src/ats/lever.py`:

```python
SUBMIT_BTN = 'button.template-btn-submit, button:has-text("Submit application")'


def missing_required(page) -> list[str]:
    """Labels of required fields that are still empty (or no checkbox ticked)."""
    missing: list[str] = []
    lis = page.locator('li')
    for i in range(lis.count()):
        li = lis.nth(i)
        label_loc = li.locator('.application-label, label').first
        if not label_loc.count():
            continue
        label = label_loc.inner_text().strip()
        if "✱" not in label and "*" not in label:
            continue
        cbs = li.locator('input[type="checkbox"]')
        if cbs.count():
            if not any(cbs.nth(j).is_checked() for j in range(cbs.count())):
                missing.append(label)
            continue
        field = li.locator('input[type="text"], input[type="email"], textarea, input[type="file"]')
        if not field.count():
            continue
        el = field.first
        if el.get_attribute("type") == "file":
            # resume: Lever shows an "uploaded" indicator; treat presence of a value as ok
            if not li.locator('.filename, [class*="resume"]').count():
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
            target = url if url.rstrip("/").endswith("/apply") else url.rstrip("/") + "/apply"
            page.goto(target)
            page.wait_for_timeout(3000)
        profile = load_profile()
        job = parse_job(page.url, page)
        job["url"] = page.url.split("?")[0]

        flags = fill_application(page, profile)
        missing = missing_required(page)
        if flags or missing:
            reason = f"Unanswered required fields: {missing or flags}"
            return _finish({"status": "blocked", "reason": reason, **job})

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


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="Lever job URL")
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


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual verification — fill only (safe)**

```bash
./venv/bin/python -m src.ats.lever --no-submit https://jobs.lever.co/hive/fb175ecc-b6ba-4242-a84a-8699f9b0e971/apply
```

Expected: prints `REVIEW - Filled; stopped before submit`; the live form is fully filled; nothing is submitted. Inspect the form in Chrome and confirm every required field is correct.

- [ ] **Step 3: Manual verification — safety brake**

Temporarily blank `requires_sponsorship` in `profile.yaml`, rerun the `--no-submit` command, and confirm the result is `BLOCKED - Unanswered required fields: [...]` naming the sponsorship question. Restore `profile.yaml` afterward.

- [ ] **Step 4: Commit**

```bash
git add src/ats/lever.py
git commit -m "feat(lever): required-field brake, submit, CLI + agent_config (#2)"
```

---

### Task 6: Route Lever through the agent dispatch

**Files:**
- Modify: `src/agent/tools.py` (function `_apply_to_job`, starts at line 41)
- Test: `tests/test_ats_detect.py` (extend) + manual

**Interfaces:**
- Consumes: `detect_ats` (Task 1), `apply_one` (Task 5).
- Produces: `_apply_to_job(url)` routes `jobs.lever.co` URLs to `lever.apply_one(url, auto_submit=True, page=...)` reusing the agent's persistent page; all other URLs keep the existing Workday path unchanged.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_ats_detect.py
def test_lever_and_workday_distinct():
    assert detect_ats("https://jobs.lever.co/x/y/apply") != detect_ats(
        "https://x.myworkdayjobs.com/job")
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `./venv/bin/pytest tests/test_ats_detect.py -v`
Expected: PASS (this guards the routing contract; it should pass on Task 1's code).

- [ ] **Step 3: Add the Lever branch to `_apply_to_job`**

At the very top of `_apply_to_job` (before the existing `from ..apply import _run_one` / Workday logic), insert:

```python
    from ..ats import detect_ats
    if detect_ats(url) == "lever":
        from ..ats.lever import apply_one
        page = _get_page()
        return apply_one(url, auto_submit=True, page=page)
```

Leave the rest of the existing function (the Workday path) unchanged.

- [ ] **Step 4: Run the full suite**

Run: `./venv/bin/pytest -v`
Expected: PASS (all prior tests plus the new ones; no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools.py tests/test_ats_detect.py
git commit -m "feat(ats): route Lever URLs through agent dispatch (#2)"
```

---

## Self-Review

**Spec coverage:**
- Goal `python -m src.ats.lever <url>` → Task 5 `main`. ✓
- Reuse browser/profile/question-engine/record/resume → Tasks 2–5 (imports from `browser`, `profile`, `questions`, `record`, `experience`). ✓
- Two-tier field strategy (standard by name / custom by label) → Tasks 2, 3, 4. ✓
- Free-form answering via profile→rules→resolver → Task 3 (`answer_custom` chains `_sensitive_answer` then `_answer_for`; resolver fallback deferred — see note below). 
- Safety brake / required-field check / auto_submit + `--no-submit` → Task 5. ✓
- Spike-level routing → Tasks 1, 6. ✓
- Testing (offline units + manual e2e) → Tasks 1–3 pytest, Tasks 4–5 manual. ✓
- Out of scope (interface, Greenhouse/Ashby, EEO, login) → none added. ✓

**Deviation from spec (intentional, flagged):** the spec listed a `resolver` (Claude/Ollama) fallback for free-form questions. The one representative form needs no LLM (sponsorship is profile-backed, GPA is profile-backed). To keep the spike honest and offline-testable, `answer_custom` returns `None`/`FLAG` for genuinely unknown free-form questions, which trips the safety brake (`blocked`) rather than guessing. Wiring the resolver is a small, well-bounded follow-up once a form actually demands it — not needed to prove the Lever path. If you want it in the spike, add it as a 4th branch in `answer_custom` before the final `return None`.

**Placeholder scan:** no TBD/TODO; every code step is complete. ✓

**Type consistency:** `FLAG` is the same sentinel imported from `src.questions` throughout; `apply_one` returns the same `{"status", "reason", **job}` dict shape `apply.py` uses; `fill_application` returns `list[str]`. ✓
