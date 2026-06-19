"""Shared ATS driver contract: the result type every driver returns and the
Protocol every driver implements."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class ApplyStatus(str, Enum):
    SUBMITTED = "submitted"
    REVIEW = "review"
    BLOCKED = "blocked"
    CAPTCHA = "captcha"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of applying to one job. `job` carries metadata (title/tenant/url/...)."""
    status: ApplyStatus
    reason: str
    job: dict

    def to_dict(self) -> dict:
        """Flat back-compat shape: {status: <str>, reason, **job}."""
        return {"status": self.status.value, "reason": self.reason, **self.job}

    @classmethod
    def from_dict(cls, d: dict) -> "ApplyResult":
        """Build from a legacy {status, reason, **job} dict."""
        d = dict(d)
        status = d.pop("status", "error")
        reason = d.pop("reason", "")
        return cls(ApplyStatus(status), reason, d)


@runtime_checkable
class ATSDriver(Protocol):
    name: str

    def apply(self, page, url: str, *, auto_submit: bool) -> ApplyResult:
        """Navigate to `url` and fill/submit one application. Driver owns navigation."""
        ...
