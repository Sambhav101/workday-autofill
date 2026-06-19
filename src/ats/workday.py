"""Workday driver: wraps the existing multi-page wizard runner in apply.py.
Navigation + the apply-button/sign-in pre-flow already live inside _run_one."""
from __future__ import annotations

from .base import ApplyResult


class WorkdayDriver:
    name = "workday"

    def apply(self, page, url: str, *, auto_submit: bool) -> ApplyResult:
        from ..apply import _run_one  # lazy: avoids import cycle (apply ↔ ats)
        page.goto(url)
        page.wait_for_timeout(5000)
        return ApplyResult.from_dict(_run_one(page, auto_submit=auto_submit))
