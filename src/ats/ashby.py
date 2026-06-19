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

    # 4. Yes/No widgets (work-auth, sponsorship, etc.) — see _fill_yesno_fields
    flags += _fill_yesno_fields(page, profile)
    return flags


def _fill_yesno_fields(page, profile: dict) -> list[str]:
    """Answer Ashby Yes/No widgets. Each is
        <div _yesno><button>Yes</button><button>No</button><input type=checkbox></div>
    with the question in the field's <label> (no for/id hook). Match the question via
    the question engine and click the matching button. Required-but-unanswerable → flag."""
    flags: list[str] = []
    widgets = page.locator('[class*="_yesno"]')
    for i in range(widgets.count()):
        w = widgets.nth(i)
        question = w.evaluate("""el => {
            const fe = el.closest('[class*="fieldEntry"]') || el.parentElement;
            const lab = fe && fe.querySelector('label');
            return (lab ? lab.innerText : (fe ? fe.innerText : '')).trim();
        }""")
        if not question:
            continue
        ans = _sensitive_answer(question, profile)
        if ans is None:
            ans = _answer_for(question)
        cb = w.locator('input[type="checkbox"]')
        required = bool(cb.count()) and _is_required(cb.first)
        if ans not in ("Yes", "No"):  # FLAG, None, or a non-yes/no rule answer
            if required:
                flags.append(f"{question[:50]!r}: needs manual answer")
            continue
        btn = w.get_by_role("button", name=ans, exact=True)
        if btn.count():
            btn.first.click()
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
        typ = (el.get_attribute("type") or "").lower()
        if typ == "checkbox":
            # Yes/No widgets are handled (and required-flagged) by _fill_yesno_fields;
            # a hidden checkbox can't distinguish "No" from unanswered, so skip here.
            continue
        if typ == "file":
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
        if own_browser:
            if b:
                b.close()
            if pw:
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
