# Public-Ready First Version — Design

**Date:** 2026-06-12
**Goal:** Make `workday-autofill` safe to publish and runnable by a stranger, without
changing the core fill engine's behavior or adding new features.

## Problem

The repo is about to be made public. Two things must be true before that:

1. **No personal data leaks.** The author's resume (work history, education, schools,
   GPAs) and username must not be discoverable in any tracked file.
2. **A stranger can run it.** A new user needs a frictionless way to supply their own
   data without touching the repo, and a default that won't auto-submit real
   applications on first run.

Git history was audited: no sensitive file (`profile.yaml`, `accounts.yaml`, etc.) was
ever committed — all are gitignored. So no history rewrite is needed. The leaks live in
**currently tracked** files.

## Non-goals

- No new core features. The open TASKS (sensitive-field LLM blocklist, graceful-failure
  handling, job-description scrape, audit log) stay open.
- No live verification against a Workday tenant (requires the author's browser + a real
  posting). "Runnable" means: clone, set up, and the program starts and reaches the
  browser-connect step.

## Changes

### 1. Scrub personal data from tracked files

| File | Leak | Fix |
|------|------|-----|
| `profile.yaml.example` | Real work history & education | Replace with a fully-fake person (John Sample, Acme/Globex, Example State University). Add `resume_path` and per-education `workday_name`/`search_term`. |
| `src/experience.py` | `SCHOOL_SEARCH_TERMS`/`SCHOOL_PICK_NAMES` (real schools); hardcoded resume path | Delete the dicts; read optional `search_term`/`workday_name` per education entry. Resume path from `profile.resume_path`; CLI `--resume` overrides. |
| `src/agent/rag.py` | `~/.claude/projects/-Users-sambhav-.../memory` path | Drop it; read repo-local `docs/widget-patterns.md` if present. |
| `src/discover.py` | Comment example `"Sambhav"` | Genericize. |

### 2. Profile becomes fully config-driven

- New `resume_path` field.
- Education entries gain optional `workday_name` (Workday's exact list name) and
  `search_term`. This is the *generic* replacement for the hardcoded school dicts: the
  school-name → Workday-list-name mapping is user-specific data, so it belongs in the
  user's profile, not in code. Falls back to the existing derive-from-name logic when
  absent.

### 3. Interactive setup — `src/setup.py` (`python -m src.setup`)

Prompts for identity, contact, links, resume path, work-authorization/sponsorship; loops
to collect work-experience and education entries (essential subfields); collects skills.
Writes `profile.yaml` (gitignored). Refuses to overwrite an existing profile without
`--force`. Sensitive EEO fields are left blank — never prompted-and-guessed in a way that
pressures the user; they remain opt-in, matching the existing "never auto-guess sensitive"
design.

### 4. Safety + docs

- `agent_config.yaml`: default `auto_submit: false` (was `true`). A public tester running
  the tool unmodified must not auto-submit real job applications.
- README quickstart: clone → venv → `playwright install` → `python -m src.setup` → launch
  Chrome → `python -m src.fill`.
- Ship `docs/widget-patterns.md` (sanitized; technical knowledge, no personal data).

## Verification

- `pytest` stays green (smoke test is untouched by these changes).
- Final `git grep` for personal identifiers (name, school, email, home path) over tracked
  files returns nothing.

## Risks

- The setup script can't validate that a Workday tenant exists or that the resume path is
  correct beyond a file-exists check — acceptable for a first version.
- Removing the school dicts means the author's own runs now rely on their `profile.yaml`
  carrying `workday_name`/`search_term`; the generated example documents these fields.
