# Workday Autofill — Tasks

Work breakdown from `DESIGN.md`. Each item small + independently shippable.
Labels: `[infra]` `[feature]` `[bug]` `[test]`.

## Milestone 7 — Public release prep ✅ DONE (2026-06-12)
- [x] `[infra]` Scrub personal data from tracked files; genericize `profile.yaml.example` to a fake person
- [x] `[feature]` Config-driven school matching (`search_term`/`workday_name` per education entry) — replaced hardcoded school dicts
- [x] `[feature]` `resume_path` in profile (removed hardcoded resume path); `--resume` overrides
- [x] `[feature]` `src/setup.py` — interactive `python -m src.setup` writes gitignored `profile.yaml`
- [x] `[infra]` Default `auto_submit: false` (don't auto-submit on a stranger's first run)
- [x] `[infra]` Bump playwright pin to >=1.50 (greenlet wheels for Python 3.13/3.14); recreate venv
- [x] `[infra]` Ship `docs/widget-patterns.md` (sanitized technical notes for the RAG agent)
- [x] `[test]` Verified: pytest green, setup script generates valid profile, no personal data in tracked files, git history clean
- Spec: `docs/superpowers/specs/2026-06-12-public-ready-design.md`

## Milestone 0 — Scaffold (workflow phase 4) ✅ DONE
- [x] `[infra]` Python 3.13 venv + `requirements.txt` (3.14 broke greenlet; pinned to 3.13)
- [x] `[infra]` `playwright install chromium` + CDP smoke test (src/browser.py, scripts/launch_chrome.sh)
- [x] `[infra]` Repo layout: `src/`, `profile.yaml.example`, `README` with launch steps
- [x] `[test]` Passing smoke test (pytest: 1 passed, CDP test auto-skips). CI deferred (prototype phase).

## Milestone 1 — Profile + resume seed (mostly done)
- [x] `[feature]` `profile.yaml` schema with explicit user-set **sensitive** section
- [x] `[feature]` Seeded `profile.yaml` from resume.tex (Adobe target)
- [ ] `[user]` Fill TODO blanks: phone, street address, postal code, work_authorization, requires_sponsorship
- [ ] `[test]` Validate a filled profile against the schema

## Milestone 1.5 — Account creation per tenant
- [x] `[feature]` `credentials` block in profile.yaml (reusable password, gitignored)
- [x] `[feature]` `src/signup.py`: fill Create Account form, pause before submit + for email verify; records tenants in accounts.yaml; signs in if account exists
- [ ] `[user]` Set `credentials.account_password` in profile.yaml
- [ ] `[test]` Validate signup fill against the live Adobe Create Account modal

## Milestone 2 — Prototype (riskiest question first) ✅ GATE PASSED
- [x] `[feature]` `src/inspect_page.py`: read-only dump of every field (automation_id, label, type, value)
- [x] `[feature]` Browser driver: Playwright `connect_over_cdp` to real Chrome, find the active Workday tab
- [x] `[feature]` Field detector via Workday `formField-*`/`menuItem` ids + label proximity
- [x] `[feature]` Widget handlers: text, radio, button dropdown, cascading typeahead multiselect (`src/widgets.py`)
- [x] `[feature]` Fill "My Information" from `profile.yaml`, then **stop** (no navigation)
- [x] `[feature]` Review report (Rich): per-field table — label, value, result
- [x] `[feature]` Per-field correction via `--set key=value` (non-interactive); auto-clears stray phone extension
- [x] **GATE PASSED:** all 13 My Information fields fill reliably on the live Adobe posting; single-field correction works
- [ ] `[test]` Add a regression test once Workday DOM fixtures are captured

## Milestone 3 — Full wizard + LLM resolver
- [x] `[feature]` My Experience page filler (`src/experience.py`): 4 jobs, 2 education, LinkedIn; per-section `--section`
- [x] `[feature]` Date spinbuttons (focus+type, month auto-advances), Add-Another blocks, degree typeahead, field-of-study (type+Enter, keyboard ArrowDown+Enter to land in focused field), close-popup via heading click
- [ ] `[skip]` Skills picker — Adobe's skill search returns "No Items" for our skills; skipped in default run
- [x] `[feature]` Résumé upload (`input[type=file]` -> set_input_files, waits for "Successfully Uploaded")
- [ ] `[feature]` Websites section (URL + Add Another) — NOT present on Adobe; implement+verify on a tenant that has it. profile.links.website/github ready.
- [x] `[feature]` Voluntary Disclosures / EEO page (`src/disclosures.py`): gender/ethnicity/veteran from profile.sensitive + accept terms
- [x] `[feature]` Self-Identify Disability CC-305 (`src/selfid.py`): name, today's date, disability status
- [x] `[feature]` Full wizard navigation via pageFooterNextButton; reached **Review page (Submit present), halted — never auto-submits**
- [x] **END-TO-END PROVEN:** full Adobe application filled across all pages, stopped at Review for human submit
- [x] `[feature]` `src/apply.py`: ONE command walks every page (detects page type), fills, clicks Next, halts at Review; stops on validation errors or unknown pages
- [x] `[feature]` `src/record.py`: application tracker — parses company/title/job_id from URL+page, logs status + date to applications.yaml (gitignored, de-duped); `--list` to view, `--status` to override. Run after you click Submit.
- [x] `[feature]` Application Questions page (`src/questions.py`): maps screening Qs by TEXT (GUID ids), keyword rules → Yes/No + checkbox group; flags unrecognized questions instead of guessing
- [x] `[feature]` Claude (`claude-sonnet-4-6`) resolver for free-text/screening fields → answer + confidence (for open-text questions keyword rules can't cover)
- [ ] `[feature]` Sensitive-field blocklist: never LLM-answer; require user-set value or skip + flag
- [ ] `[feature]` Job description scrape from posting page (paste-text fallback) to feed the resolver
- [ ] `[feature]` Extend correction loop: "redo this LLM answer" with a hint → refills just that field
- [ ] `[feature]` Persist audit log per application (every field, source, confidence, your corrections)

## Milestone 4 — Robustness (multi-tenant)
- [ ] `[test]` Run against 3–4 different company Workday tenants; log gaps
- [ ] `[feature]` Graceful "couldn't fill X — do it manually" instead of crashing
- [ ] `[feature]` Resume mid-application / session-timeout recovery

## Milestone 6 — Phone control (v2, after core engine works)
- [ ] `[feature]` Mac pushes a notification when filled + paused at Review (ntfy.sh / Telegram)
- [ ] `[feature]` Phone-facing approve view: shows filled fields + low-confidence flags
- [ ] `[feature]` "Approve & Submit" from phone triggers the final Submit (no blind auto-submit)
- [ ] `[infra]` Keep-awake / debug-Chrome-running precondition handling

## Feature requests (backlog)
- [ ] `[enhancement]` **Automate email-link steps via Gmail connector** — on password reset /
  account verification, read Gmail, extract the Workday reset/verify link, open it, set password.
  Reverses the earlier "verification stays manual" decision. **Tradeoff:** grants the tool read
  access to the user's Gmail. Also unlocks auto password-reset. Requires Gmail auth + `email_links.py`.

## Milestone 5 — Productionize (when prototype proves out)
- [ ] `[infra]` Error handling, logging, packaging, README
- [ ] `[test]` Test suite for mapper + resolver guardrails
- [ ] `[infra]` Tighten CI as a blocking gate
