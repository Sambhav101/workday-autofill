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
