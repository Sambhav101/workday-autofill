# Lever ATS Spike — Design Doc

**Date:** 2026-06-19
**Issue:** #2 (Support Greenhouse, Lever, and Ashby job applications)
**Status:** Approved — ready for implementation plan

## Context

The autofill pipeline today is Workday-only. `apply.py` is not a generic engine
with a Workday plugin — it *is* the Workday driver: the page-by-page wizard state
machine (`PAGE_CHECKS` → fill → `pageFooterNextButton` → Review → Submit), the
mandatory account creation/sign-in (`signup.py`), and per-page fillers
(`fill.py`, `experience.py`, `questions.py`, `disclosures.py`, `selfid.py`) all
keyed to Workday's `data-automation-id` selectors and Workday's page split.

Greenhouse, Lever, and Ashby have a fundamentally different shape: a **single-page
form, no account, one Submit button**. Most of `apply.py`'s complexity does not
apply to them.

### Why a spike first (approach C)

We considered three approaches:

- **A. Extract a clean `ATSDriver` interface now**, refactor Workday into its first
  implementation, then add the others. Rejected as the *first* step: we have exactly
  one ATS today and it is the weird one (multi-page wizard + account). Designing the
  universal interface around Workday risks the wrong abstraction.
- **B. Minimal — add standalone fillers alongside an untouched `apply.py`.** Fast,
  but produces two diverging code paths and duplicated dedup/reporting/queue logic.
- **C. Build Lever (the simplest ATS) end-to-end first as a spike, then extract the
  interface from two real, different shapes.** Chosen. Costs one small rewrite of
  Lever later, which is cheap because Lever is a single form. Matches "validate
  cheap before expensive."

This doc covers **only the Lever spike**. The interface extraction (A) and
Greenhouse/Ashby are explicitly deferred to follow-up specs.

## Reference: the real Lever form

Grounded against a live posting (Hive — Machine Learning Engineer,
`jobs.lever.co/hive/fb175ecc-b6ba-4242-a84a-8699f9b0e971/apply`), captured
2026-06-19. Structure:

- **Submit your application:** Resume/CV upload (required), Full name\*, Email\*,
  Phone\*, Current location, Current company
- **Links:** LinkedIn / Twitter / GitHub / Portfolio / Other website (all optional)
- **Additional Questions** (per-job, custom): "What is/was your GPA?"\* (text),
  "Will you now or in the future require sponsorship…?"\* (free-form textarea)
- **How did you hear about Hive?:** checkbox group\* (Friend / Recruiter / LinkedIn /
  …) + "If Other, please specify" text
- One **Submit application** button. No account, no wizard. **No EEO section on this
  posting** (Lever EEO is per-customer and absent here).

Required fields are marked `✱`. With auto-submit, *every* required field must be
answered or Submit fails — so custom-question answering is mandatory, not optional.

## Goals

- `python -m src.ats.lever <url>` fills and (per config) auto-submits a Lever
  application from `profile.yaml`.
- Reachable from the existing batch runner, web UI, and extension queue via a
  spike-level URL check.
- Reuse the existing question-answering engine, browser connection, profile loader,
  and application recorder.

## Non-goals / out of scope (spike)

- The `ATSDriver` interface / refactor of `apply.py` (next phase).
- Greenhouse and Ashby (separate specs).
- EEO/demographic handling (this form has none; add when we hit a form that does).
- Account creation / login (Lever has none).
- A production-grade multi-ATS router (spike uses a simple URL check).

## Architecture

New module `src/ats/lever.py`, standalone (deliberately **not** behind an interface
yet — that is the point of the spike).

Reused without rewrite:

- `browser.py` — CDP connect, `find_any_tab`
- `profile.py` — `load_profile`
- Question engine — `questions.py` (`_answer_for`, `_sensitive_answer`,
  `_work_auth_answer`, `_yes_no`), `screening_rules.yaml`, `resolver.py`. These key
  on **question label text**, not Workday `aid`s, so they port to Lever's custom
  questions as-is.
- `record.py` — log submitted applications to `applications.yaml`
- Resume upload via `input[type=file]` — prior art in `experience.py`

### Field strategy — two tiers

1. **Standard fields by stable `name` attribute.** Lever's built-in inputs have
   fixed `name`s (e.g. `name`, `email`, `phone`, `org`, `urls[LinkedIn]`, and resume
   as an `input[type=file]`). Map `profile.yaml` → these directly. **Exact attribute
   names are verified from the live DOM during implementation, never assumed from
   memory.**

2. **Custom "Additional Questions" by label text.** These have dynamic `name`s
   (`cards[...]`), so they are matched on the visible question label, then routed
   through the existing question engine. Widget types to handle: single-line text,
   textarea (free-form), checkbox group; radios/selects appear on other postings and
   are handled with the same label-based approach.

### Answering questions (the hard part)

Order of resolution for each required custom question:

1. Profile-backed structured answers (`_sensitive_answer` for work
   auth/sponsorship; GPA / grad date / salary from profile `preferences`/education).
2. Keyword rules from `screening_rules.yaml` via `_answer_for`.
3. Free-form fallback via the `resolver` (Claude/Ollama per `agent_config.yaml`).
4. "How did you hear about us" → a configurable default selection (e.g. "LinkedIn").

If a **required** field cannot be answered confidently by any of the above, the
field is left empty and flagged.

### Submit + safety brake

- Before submitting, enumerate required (`✱`) fields and verify each is filled
  (mirrors `apply.py:_check_required_fields`).
- **If any required field is unanswered → refuse to auto-submit, stop, and report
  which fields are missing.** This is the one irreversible action in the system.
- Honor `agent_config.yaml: auto_submit` and a `--no-submit` CLI flag. Recommended
  practice: first run on any new job uses `--no-submit` to review before trusting.
- On successful submit, record to `applications.yaml` via `record.py`.

### Routing (spike-level)

Entry point checks the URL host: `jobs.lever.co` → Lever driver, otherwise existing
Workday path. A real multi-ATS router is deferred to the interface phase.

## Data flow

```
URL (jobs.lever.co/...)
  → browser.connect + find_any_tab (existing CDP Chrome)
  → navigate to <url>/apply
  → discover form: standard fields (by name) + custom questions (by label)
  → fill standard fields from profile.yaml
  → answer custom questions (profile → rules → resolver)
  → upload resume (input[type=file])
  → verify all required (✱) fields filled
      ├─ all filled + auto_submit → click Submit → record to applications.yaml
      ├─ all filled + --no-submit → stop, report "ready to submit"
      └─ missing required → stop, report missing fields (never submit)
```

## Failure modes / risks

- **Auto-submitting a half-understood form** → the required-field verification brake
  + `--no-submit` first-run practice. The brake refuses submit rather than sending a
  bad application.
- **Resolver gives a wrong free-form answer** → mitigated by `--no-submit` review on
  first run; the answer is shown before submit.
- **Lever DOM differs across postings** (custom questions, EEO present on some) →
  label-based matching is resilient; unknown required fields are flagged, not
  guessed. EEO handling deferred until a form with it is the target.
- **Selector assumptions wrong** → all `name`/selector specifics are verified against
  the live DOM during implementation, and covered by a saved-DOM fixture test.

## Testing

- **Unit (offline):** save the Hive form DOM as a fixture; test profile→standard-field
  mapping and custom-question routing without network.
- **Manual e2e:** run against the live Hive URL with `--no-submit` first; confirm
  every field fills correctly and the required-field check passes before any real
  submit.

## Rollout

1. Implement `src/ats/lever.py` + URL check at the entry point.
2. Validate manually with `--no-submit` on the Hive posting (and one other Lever
   posting if available) before any auto-submit.
3. Once Lever is proven, open the follow-up spec to extract the `ATSDriver`
   interface from Workday + Lever, then add Greenhouse and Ashby.

## Open questions

- Default answer for "How did you hear about us?" — proposed default "LinkedIn",
  overridable in config. Confirm during implementation.
- Resume file path source in `profile.yaml` — confirm the existing key used by
  `experience.py` and reuse it.
