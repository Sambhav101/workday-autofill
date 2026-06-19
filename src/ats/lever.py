"""Lever ATS driver (spike). Single-page form: fill from profile.yaml, then
optionally auto-submit. Standalone — not behind an ATSDriver interface yet.

    ./venv/bin/python -m src.ats.lever <url>                 # fill, then submit per config
    ./venv/bin/python -m src.ats.lever --no-submit <url>     # fill only, stop before submit
"""
from __future__ import annotations

from ..questions import _answer_for, _sensitive_answer, FLAG
from ..experience import upload_resume


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


def _fill_text_by_name(page, name: str, value: str) -> bool:
    loc = page.locator(f'[name="{name}"]')
    if not loc.count():
        return False
    loc.first.fill(value)
    return True


def _custom_cards(page):
    """Return list of (card_li, label_text, kind) for each custom question.
    kind is 'text', 'textarea', or 'checkbox'."""
    cards = page.locator('li.application-question.custom-question')
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
            # resume present iff the input actually has a file queued
            has_file = el.evaluate("e => !!(e.files && e.files.length)")
            if not has_file:
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
            reason = f"Unanswered required fields — missing: {missing}; flagged: {flags}"
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
