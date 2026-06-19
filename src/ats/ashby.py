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
