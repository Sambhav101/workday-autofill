# Workday Autofill

Playwright-based automation that fills Workday job applications from `profile.yaml`.

## Quick Reference

- **Venv**: `./venv/bin/python`
- **Launch Chrome**: `bash scripts/launch_chrome.sh` (CDP port 9222, separate profile at `~/Library/Application Support/workday-autofill-chrome`)
- **Signup**: `./venv/bin/python -m src.signup` (create account or sign in on tenant)
- **Apply (single)**: `./venv/bin/python -m src.apply --submit URL` (fill + submit + record)
- **Apply (batch)**: `./venv/bin/python -m src.apply --submit URL1 URL2 ...` (batch mode, report saved to `report.yaml`)
- **Apply (current tab)**: `./venv/bin/python -m src.apply` (fill whatever tab is open, stop at Review)
- **Record**: `./venv/bin/python -m src.record` (log submission after manual Submit)

## Architecture

Connects to user's Chrome via CDP (port 9222). Requires Chrome launched with `--remote-debugging-port=9222`.

**Pipeline**: launch Chrome -> navigate to URL -> Apply/Continue Application -> popup (Apply Manually) -> signup (create/sign-in/forgot-password) -> fill pages (detect -> discover -> fill -> check required -> Next) -> Submit + record.

**Key modules** (`src/`):
- `browser.py` — CDP connection, find Workday tab
- `signup.py` — account create / sign-in / forgot-password per tenant; handles verify-then-signin flow
- `apply.py` — page detection loop, batch runner (`run_batch`), `_run_one` per job
- `fill.py` — My Information page (discover-based widget dispatch)
- `experience.py` — work/education/skills/resume + `_verify_education` post-fill check
- `questions.py` — application questions via keyword rules + LLM resolver fallback + text fields
- `disclosures.py` — EEO (gender, hispanic/latino, race checkbox, veteran, terms)
- `selfid.py` — disability self-identification
- `widgets.py` — low-level Workday widget helpers (`_safe_click`, `select_multiselect_by_label`, `_poll`)
- `discover.py` — DOM scanner, run before filling any page
- `profile.py` — loads `profile.yaml`
- `record.py` — logs completed applications to `applications.yaml`

## Data Files

- `profile.yaml` — identity, work history, education, skills, credentials, sensitive/EEO info
- `accounts.yaml` — tracks which tenants have accounts created
- `applications.yaml` — submitted application log
- `report.yaml` — batch run results (status, blockers, reasons per job)

## Critical Rules

- **Education accuracy**: Degree must be MS/Master of Science for Master's, BS/Bachelor of Science for Bachelor's. Short codes (BS, MS, etc.) use exact matching via `_DEGREE_EXACT`. Field of study must strictly match FIELD_VARIANTS (no fuzzy matching). `_verify_education` runs after fill to catch and fix mismatches.
- **No blind first-option fallbacks**: Never pick the first dropdown option as a guess. Return failure instead.
- **Discover before filling**: Always run `discover_page`/`discover_fields` before any filler.
- **Check required fields before Next**: `_check_required_fields()` must pass (returns `[]`) before clicking Next. Checkbox groups check actual `is_checked()` state, not value strings.
- **Fill all sections, even optional ones**: Work history, education, skills — fill them even when headed "(Optional)". Section headings vary: "Work History" vs "Work Experience".
- **Continue Application**: Revisiting a partially-filled job shows "Continue Application" link instead of Apply button. Handle both.
- **Email verify vs password verify**: Only return `pending_verify` when page has email verification phrases ("check your email", "verify your email"). Never match "Verify Password" field labels.
- **Dropdown fallbacks**: Rules in `questions.py` support `"val1|val2|val3"` pipe-separated fallbacks for ordered alternative answers.
- **Blockers don't stop batch**: Assessment pages, validation errors, etc. are logged to `report.yaml` and the pipeline moves to the next job.
- Default: stop at Review page. Use `--submit` flag to submit + record atomically.
- See parent `../CLAUDE.md` for project workflow, git, and data safety rules.
- No `Co-Authored-By` in commits.
