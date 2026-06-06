"""Field registry: maps Workday automation-ids and label patterns to profile data.

This is the single source of truth for "what field is this and what value goes
in it." Instead of each page filler hardcoding its own field list, every filler
asks the registry: given this automation-id (or label), what profile value and
fill strategy should I use?

The registry works in two tiers:
  1. automation-id exact match (fast, stable across tenants)
  2. label pattern match (fallback for tenant-specific or GUID-keyed fields)

Each entry specifies:
  - profile_path: dot-separated path into profile.yaml (e.g. "identity.first_name")
  - widget: expected widget type ("text", "dropdown", "multiselect", "radio", etc.)
  - transform: optional callable to transform the profile value before filling
  - match_labels: list of label substrings for fallback matching
  - skip_if_set: if True, don't overwrite existing values
"""
from __future__ import annotations

from typing import Any, Callable

from .widgets import US_STATES


def _state_full(val: str) -> str:
    return US_STATES.get(str(val).upper(), val)


def _phone_str(val: Any) -> str:
    return str(val).strip()


def _disability_label(val: str) -> str:
    s = str(val).strip().lower()
    if s in ("no", "false", "n"):
        return "No, I do not have a disability"
    if s in ("yes", "true", "y"):
        return "Yes, I have a disability"
    return "I do not want to answer"


def _veteran_label(val: str) -> str:
    s = str(val).strip().lower()
    if s.startswith("not"):
        return "not a veteran"
    return val


class FieldEntry:
    __slots__ = ("profile_path", "widget", "transform", "match_labels",
                 "skip_if_set", "value_override", "cascade")

    def __init__(self, profile_path: str, widget: str, *,
                 transform: Callable | None = None,
                 match_labels: list[str] | None = None,
                 skip_if_set: bool = False,
                 value_override: str | None = None,
                 cascade: bool = False):
        self.profile_path = profile_path
        self.widget = widget
        self.transform = transform
        self.match_labels = match_labels or []
        self.skip_if_set = skip_if_set
        self.value_override = value_override
        self.cascade = cascade

    def resolve_value(self, profile: dict) -> str:
        if self.value_override is not None:
            return self.value_override
        val = _get_nested(profile, self.profile_path)
        if val is None:
            return ""
        val = str(val)
        if self.transform:
            val = self.transform(val)
        return val


def _get_nested(d: dict, path: str) -> Any:
    parts = path.split(".")
    cur = d
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
        if cur is None:
            return None
    return cur


# ── The registry ────────────────────────────────────────────────────────────
# Keyed by automation-id (without the "formField-" prefix for readability,
# but stored with full aid in the lookup dict).

_ENTRIES: dict[str, FieldEntry] = {}


def _reg(aid: str, profile_path: str, widget: str, **kw):
    _ENTRIES[f"formField-{aid}"] = FieldEntry(profile_path, widget, **kw)


# ── My Information fields ───────────────────────────────────────────────────

_reg("legalName--firstName", "identity.first_name", "text",
     match_labels=["first name"])
_reg("legalName--lastName", "identity.last_name", "text",
     match_labels=["last name"])
_reg("legalName--preferredName", "identity.preferred_name", "text",
     match_labels=["preferred name"], skip_if_set=True)
_reg("country", "contact.country", "dropdown",
     value_override="United States of America",
     match_labels=["country"])
_reg("addressLine1", "contact.address_line1", "text",
     match_labels=["address line 1", "street address"])
_reg("city", "contact.city", "text",
     match_labels=["city"])
_reg("countryRegion", "contact.state", "dropdown",
     transform=_state_full,
     match_labels=["state", "region", "province"])
_reg("postalCode", "contact.postal_code", "text",
     transform=str,
     match_labels=["postal code", "zip"])
_reg("emailAddress", "identity.email", "text",
     match_labels=["email"], skip_if_set=True)
_reg("phoneType", "", "dropdown",
     value_override="Mobile",
     match_labels=["phone device type", "phone type"])
_reg("phoneNumber", "identity.phone", "text",
     transform=_phone_str,
     match_labels=["phone number"])
_reg("extension", "", "text",
     value_override="",
     match_labels=["extension"])
_reg("candidateIsPreviousWorker", "", "radio",
     value_override="No",
     match_labels=["previously worked", "previous worker", "prior employee"])
_reg("source", "preferences.how_did_you_hear", "multiselect",
     cascade=True,
     match_labels=["how did you hear"])
_reg("countryPhoneCode", "", "multiselect",
     value_override="United States of America (+1)",
     match_labels=["country phone code", "phone code"])

# ── Voluntary Disclosures (EEO) ────────────────────────────────────────────

_reg("gender", "sensitive.gender", "dropdown",
     match_labels=["gender"])
_reg("ethnicity", "sensitive.race_ethnicity", "dropdown",
     match_labels=["ethnicity", "race"])
_reg("veteranStatus", "sensitive.veteran_status", "dropdown",
     transform=_veteran_label,
     match_labels=["veteran"])
_reg("acceptTermsAndAgreements", "", "checkbox",
     value_override="checked",
     match_labels=["accept terms", "agree"])

# ── Self-Identification (CC-305) ───────────────────────────────────────────

_reg("name", "", "text",
     match_labels=["your name", "signature"])
_reg("disabilityForm", "sensitive.disability_status", "radio",
     transform=_disability_label,
     match_labels=["disability"])

# ── My Experience — these are repeated per entry, handled by index ─────────

_reg("jobTitle", "work_experience.{i}.title", "text",
     match_labels=["job title"])
_reg("companyName", "work_experience.{i}.company", "text",
     match_labels=["company"])
_reg("location", "work_experience.{i}.location", "text",
     match_labels=["location"])
_reg("startDate", "work_experience.{i}.start", "date",
     match_labels=["start date", "from"])
_reg("endDate", "work_experience.{i}.end", "date",
     match_labels=["end date", "to"])
_reg("currentlyWorkHere", "work_experience.{i}.current", "checkbox",
     match_labels=["currently work here", "current"])
_reg("roleDescription", "work_experience.{i}.bullets", "text",
     match_labels=["description", "role description"])

_reg("schoolName", "education.{i}.school", "text",
     match_labels=["school name"])
_reg("school", "education.{i}.school", "text",
     match_labels=["school"])
_reg("degree", "education.{i}.degree", "dropdown",
     match_labels=["degree"])
_reg("fieldOfStudy", "education.{i}.field", "multiselect",
     match_labels=["field of study", "major"])
_reg("gradeAverage", "education.{i}.gpa", "text",
     match_labels=["gpa", "grade"])
_reg("firstYearAttended", "education.{i}.start", "date",
     match_labels=["first year"])
_reg("lastYearAttended", "education.{i}.end", "date",
     match_labels=["last year"])

_reg("websiteAddress", "links", "text",
     match_labels=["website", "url"])
_reg("linkedInAccount", "links.linkedin", "text",
     match_labels=["linkedin"])


# ── Lookup functions ────────────────────────────────────────────────────────

def lookup_by_aid(aid: str) -> FieldEntry | None:
    return _ENTRIES.get(aid)


def lookup_by_label(label: str) -> FieldEntry | None:
    if not label:
        return None
    label_low = label.lower()
    best = None
    best_score = 0
    for entry in _ENTRIES.values():
        for pattern in entry.match_labels:
            if pattern in label_low:
                score = len(pattern)
                if score > best_score:
                    best = entry
                    best_score = score
    return best


def lookup(aid: str, label: str = "") -> FieldEntry | None:
    return lookup_by_aid(aid) or lookup_by_label(label)


def all_entries() -> dict[str, FieldEntry]:
    return dict(_ENTRIES)
