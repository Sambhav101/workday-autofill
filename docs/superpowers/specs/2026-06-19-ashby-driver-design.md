# Ashby Driver — Design Doc

**Date:** 2026-06-19
**Issue:** #2 (third ATS, after Lever PR #7 and the ATSDriver interface PR #9)
**Status:** Approved — ready for implementation plan

## Context

The `ATSDriver` interface now exists (`src/ats/base.py`, `dispatch`/`run_batch`,
`_REGISTRY`), with Workday and Lever as the two implementations. Adding an ATS is now
"one driver class + one registry line + one `detect_ats` host pattern" plus the
ATS-specific form logic. This spec adds **Ashby** (`jobs.ashbyhq.com`).

Ashby is single-page, no account, captcha-gated — the same shape as Lever — so it
mirrors `LeverDriver` rather than the Workday wizard.

### Reference: the real Ashby form

Grounded against a live posting (The Voleon Group — Senior ML Engineer,
`jobs.ashbyhq.com/voleon/e5c0863d-1371-4790-a50f-b467fa544b08/application`), captured
2026-06-19:

- **Stable system fields:** `#_systemfield_name` (Full Name, required),
  `#_systemfield_email` (Email, required), and the resume file input
  `#_systemfield_resume`.
- **Per-job custom fields with UUID `name`s, matched by label text:** Phone Number,
  Current Location, Current Company, LinkedIn, GitHub, Portfolio, Other.
- **Work-auth / sponsorship:** checkbox-style fields labeled with the question
  ("Are you legally authorized to work in the United States?", "Will you now or in
  the future require visa sponsorship?"), answered from `profile.sensitive`.
- **Free-form:** a "sponsorship details" textarea (optional).
- **Captcha:** reCAPTCHA (`g-recaptcha-response` present) — gates submission.
- **Resume gotcha:** there are **two** file inputs — an "Autofill from resume"
  uploader (Ashby's own resume-parsing feature) *and* the real `#_systemfield_resume`.
  The driver must target `#_systemfield_resume`, not the first `input[type=file]`.

### The Ashby difference from Lever

In Lever, standard fields had stable `name` attributes (`name`, `email`, `phone`,
`urls[LinkedIn]`). In Ashby, **only name/email/resume are stable; everything else is a
per-job UUID field matched by label text.** So Ashby leans even harder on label-based
matching and the shared question engine.

## Goals

- `python -m src.ats.ashby <url>` and the unified `dispatch`/`run_batch` fill and
  (per config) submit an Ashby application from `profile.yaml`.
- Ashby reachable through the existing `dispatch` (so the agent, web runner, and CLI
  all handle it with no further wiring).
- Reuse the question engine, profile loader, recorder, the `ATSDriver`/`ApplyResult`
  contract, and a newly-shared captcha helper.

## Non-goals / out of scope

- A broader single-page form-fill helper shared between Lever and Ashby. Deferred
  until Greenhouse (the 3rd single-page case) confirms the common shape — extracting
  from two examples risks the wrong abstraction.
- Greenhouse driver (separate spec).
- Web UI status-dot styling for `captcha`/`review` (tracked in #8).
- Ashby's "Autofill from resume" feature — deliberately bypassed.

## Architecture

### Component 1 — shared captcha helper (`src/ats/captcha.py`, new)

Extract the captcha detection currently living in `src/ats/lever.py` into a shared
module, since Ashby needs the identical check:

```python
CAPTCHA_SEL = ('#h-captcha, .h-captcha, iframe[src*="hcaptcha"], '
               '.g-recaptcha, iframe[src*="recaptcha"], '
               'iframe[src*="turnstile"], textarea[name="g-recaptcha-response"]')

def has_captcha(page) -> bool:
    """True if the form shows an hCaptcha/reCAPTCHA/Turnstile challenge."""
    return page.locator(CAPTCHA_SEL).count() > 0
```

`src/ats/lever.py` is refactored to import `has_captcha`/`CAPTCHA_SEL` from here and
drop its local copies (behavior unchanged — the selector is a superset of Lever's
current one). Ashby imports the same. Single source of truth, no drift.

### Component 2 — the driver (`src/ats/ashby.py`, new)

Mirrors `src/ats/lever.py`'s structure:

- Pure helpers: `ashby_job_meta(url)` (parse `company`/`job_id` from
  `jobs.ashbyhq.com/<company>/<job-id>`), plus profile→value mapping reusing the same
  `standard_field_values`-style logic and the existing question engine.
- Browser functions: `fill_application(page, profile) -> list[str]` (fill stable
  fields by selector + custom fields by label, upload resume to `#_systemfield_resume`,
  answer work-auth/sponsorship from `profile.sensitive`), `missing_required(page)`
  (required-field brake), `submit(page)`, `apply_one(url, *, auto_submit, page)`.
- `class AshbyDriver` with `name = "ashby"` and `apply(self, page, url, *, auto_submit)`
  delegating to `apply_one` and wrapping via `ApplyResult.from_dict`.

Field strategy:
- Name/email by `#_systemfield_name` / `#_systemfield_email`.
- Resume via `#_systemfield_resume` specifically (NOT the first `input[type=file]`).
- All other fields by label text → the existing question/profile routing
  (`answer_custom`/`_sensitive_answer`/`_answer_for`).

### Component 3 — registry + routing (one line each)

- `src/ats/__init__.py:detect_ats` — add `if "jobs.ashbyhq.com" in host: return "ashby"`.
- `src/ats/__init__.py:_REGISTRY` — add `"ashby": AshbyDriver()`.

No consumer changes — `dispatch`/`run_batch`/agent/web/CLI route Ashby automatically.

## Data flow

```
jobs.ashbyhq.com/<company>/<job-id> ──> dispatch
  └─ detect_ats → "ashby" → AshbyDriver.apply
       └─ apply_one: goto <url>/application
            → fill #_systemfield_name / _email
            → upload resume to #_systemfield_resume
            → fill custom fields by label (phone/location/company/links/work-auth/...)
              via the question engine + profile
            → missing_required (✱) brake
            → has_captcha? → status "captcha" (fill + stop)
            → else auto_submit ? submit + record : "review"
       └─ ApplyResult{status, reason, job}
```

## Failure modes / risks

- **React controlled inputs** — Playwright `.fill()` normally fires React's onChange,
  but if a field's value reverts, fall back to `.type()` or a native-setter + `input`
  event dispatch. Confirmed against the live form during implementation.
- **Work-auth/sponsorship widget shape** — the snapshot shows these as checkboxes
  labeled with the question; the exact widget (checkbox vs radio/select) and Yes/No
  mapping is confirmed against the live DOM during implementation, the same way Lever's
  checkbox group was nailed during its spike.
- **Wrong resume input** — targeting the first `input[type=file]` would hit Ashby's
  "Autofill from resume" uploader; mitigated by the explicit `#_systemfield_resume`
  selector.
- **Captcha blocks submit** — expected; `has_captcha` → `captcha` status (fill + stop),
  same as Lever. reCAPTCHA is in the shared `CAPTCHA_SEL`.
- **Location autocomplete rewrites value** — same as Lever (optional field); accepted.

## Testing

- **Unit (offline):** `detect_ats`/`driver_for` for an Ashby URL; `ashby_job_meta`
  URL parsing; `has_captcha` selector set (in `captcha.py`, incl. reCAPTCHA); pure
  profile→value / label→answer mapping; `AshbyDriver` via monkeypatch. Plus: confirm
  Lever's refactor onto shared `captcha.py` keeps its tests green.
- **Live (manual, before merge):** the Voleon ML-Eng form with `--no-submit` —
  fields fill, resume targets `#_systemfield_resume`, reCAPTCHA → `captcha` status.

## Rollout

1. Extract `src/ats/captcha.py`; refactor Lever onto it (tests stay green).
2. Build `src/ats/ashby.py` (pure helpers + browser fill + `AshbyDriver`) with unit
   tests.
3. Wire `detect_ats` + `_REGISTRY` (one line each).
4. Live-verify the Voleon form with `--no-submit`.
5. Merge. Greenhouse follows as a separate spec; the shared form-fill helper extraction
   is revisited then.

## Open questions

None — scope (standalone Ashby + extract captcha only), the field strategy
(label-based + stable name/email/resume), and the deferred form-fill extraction are
resolved. The React-fill technique and the work-auth widget shape are
implementation-time confirmations against the live DOM, not open design questions.
