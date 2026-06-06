"""Runtime LLM resolver for employer-specific application questions that the
keyword rules in questions.py can't cover. Uses Claude Sonnet 4.6 to pick an
answer from the question's *actual* options, grounded ONLY in profile.yaml.

Guardrails:
- Must choose one of the provided options (or "UNSURE").
- Never invents facts about the candidate; unsupported -> "UNSURE" -> flagged
  for the human, never auto-answered.
- Sensitive topics (visa, criminal history, salary, EEO) only answered if a
  profile fact directly addresses them.

Degrades gracefully: if ANTHROPIC_API_KEY is unset, returns UNSURE so the field
is flagged for manual entry instead of failing.
"""
from __future__ import annotations

import json
import os

from .profile import load_profile

MODEL = "claude-sonnet-4-6"  # chosen in DESIGN.md

SYSTEM = (
    "You fill out job-application screening questions on behalf of a candidate, "
    "using ONLY the provided profile facts. Choose exactly one of the provided "
    "options. If the profile does not directly support a confident answer, set "
    "answer to 'UNSURE'. Never invent facts about the candidate. For legally or "
    "strategically sensitive topics (visa sponsorship, work authorization, "
    "criminal history, salary, EEO/disability/veteran), answer only if a profile "
    "fact directly addresses it; otherwise 'UNSURE'."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "Exactly one provided option, or 'UNSURE'"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["answer", "confidence", "reason"],
    "additionalProperties": False,
}


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _profile_summary(p: dict) -> str:
    ident = p.get("identity", {})
    contact = p.get("contact", {})
    sens = p.get("sensitive", {})
    prefs = p.get("preferences", {})
    jobs = p.get("work_experience", [])
    lines = [
        f"Name: {ident.get('first_name')} {ident.get('last_name')}",
        f"Location: {contact.get('city')}, {contact.get('state')}, {contact.get('country')}",
        f"Work authorization: {sens.get('work_authorization')}",
        f"Requires visa sponsorship: {sens.get('requires_sponsorship')}",
        f"Willing to relocate: {prefs.get('willing_to_relocate')}",
        f"Earliest start date: {prefs.get('earliest_start_date')}",
        f"Desired salary: {prefs.get('desired_salary')}",
        f"Years of experience (approx): {len(jobs)} roles incl. {', '.join(j.get('company','') for j in jobs[:4])}",
        f"Most recent title: {jobs[0].get('title') if jobs else 'n/a'}",
        f"Education: " + "; ".join(f"{e.get('degree')} {e.get('field')}" for e in p.get('education', [])),
    ]
    return "\n".join(lines)


def resolve_choice(question: str, options: list[str], job_title: str = "") -> dict:
    """Return {answer, confidence, reason}. answer is one of options or 'UNSURE'."""
    if not available():
        return {"answer": "UNSURE", "confidence": 0.0, "reason": "no ANTHROPIC_API_KEY set"}
    try:
        import anthropic
    except ImportError:
        return {"answer": "UNSURE", "confidence": 0.0, "reason": "anthropic SDK not installed"}

    prof = _profile_summary(load_profile())
    prompt = (
        f"Candidate profile facts:\n{prof}\n\n"
        f"Job: {job_title or 'unknown'}\n\n"
        f"Question: {question}\n"
        f"Options (choose exactly one, or 'UNSURE'): {json.dumps(options)}\n\n"
        "Respond with JSON: {answer, confidence (0-1), reason}."
    )
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        text = next(b.text for b in resp.content if b.type == "text")
        data = json.loads(text)
        # validate the answer is an offered option (or UNSURE)
        if data.get("answer") not in options and data.get("answer") != "UNSURE":
            return {"answer": "UNSURE", "confidence": 0.0,
                    "reason": f"model returned non-option {data.get('answer')!r}"}
        return data
    except Exception as e:  # noqa: BLE001
        return {"answer": "UNSURE", "confidence": 0.0, "reason": f"resolver error: {e}"}
