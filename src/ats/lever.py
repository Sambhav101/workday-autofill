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
