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
