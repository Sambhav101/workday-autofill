# workday-autofill

Autofill Workday job applications by driving your **own logged-in Chrome**, with
an option to **pause at the final Submit** so you review before anything is sent.

## Why

Workday makes you re-enter everything: upload a resume it parses wrong, re-type it
all by hand, create yet another account, re-key the work history that's sitting in
the PDF you just gave it. After the fortieth application I'd rather automate the
tedious parts than do them one more time, and the fix shouldn't mean handing my
logins to some cloud service.

## How it works

- Connects to your **real Chrome** over the DevTools Protocol, so it reuses your
  existing sessions and cookies. No headless login, no password of its own, and it
  works behind whatever SSO you're already signed into.
- Reads your details from a single editable `profile.yaml` (gitignored), seeded
  from your resume.
- Detects Workday's fields and fills text, dropdowns, and cascading typeaheads,
  then prints a per-field review table so you see exactly what it set.
- `auto_submit` in `agent_config.yaml` controls the last step: leave it off to
  stop before Submit and review, or turn it on to submit automatically.

## How questions get answered

Workday's "Application Questions" page is where the tool is deliberately
conservative, because some answers are legally binding:

- **Common questions** (over 18, background check, non-compete, arbitration,
  "have you worked here before") use keyword rules in **`screening_rules.yaml`** — a
  plain editable file. The shipped defaults are common-but-not-universal; change any
  answer (e.g. arbitration), or delete a rule to have that question flagged for you
  to answer by hand. No code editing required.
- **Visa / work-authorization / citizenship** come straight from your
  `profile.yaml` `sensitive:` block (`work_authorization`, `requires_sponsorship`).
  If your profile doesn't clearly answer a question, it is **flagged for you to
  answer manually** — never guessed. Citizenship is never inferred from work
  authorization (being authorized to work ≠ being a citizen).
- **Salary, graduation date, GPA, start date** come from your profile
  (`preferences.desired_salary`, your education entries). Blank in the profile →
  flagged, not filled with a made-up number.
- **EEO / diversity** (gender, race, veteran, disability) are filled only from the
  `sensitive:` block; leave a field blank to decline it. Nothing is ever guessed.
- **Anything else** goes to an optional LLM resolver, grounded only in your profile.
  Set `ANTHROPIC_API_KEY` to enable it (or point it at a local Ollama model in
  `agent_config.yaml`). With no key, novel questions are flagged for manual entry.

Every run prints a per-field review table and **stops before Submit** by default,
so you can fix anything flagged before anything is sent.

## Setup

Requires Python 3.13 or 3.14.

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/playwright install chromium
```

Then create your profile (gitignored — never enters the repo):

```bash
./venv/bin/python -m src.setup      # interactive prompts -> profile.yaml
```

Prefer to edit a file by hand? Copy the sample instead:

```bash
cp profile.yaml.example profile.yaml   # then edit it
```

Set `resume_path` in `profile.yaml` to your resume PDF so the tool can upload it.

## Filling in your details (walkthrough)

Everything personal lives in **`profile.yaml`** (gitignored). `python -m src.setup`
prompts you through it; here's what each part feeds and what you can leave blank.

**1. Identity, contact, links, resume.** Name, email, phone, address, LinkedIn/site/
GitHub, and `resume_path` (the PDF Workday uploads). These fill the "My Information"
and "My Experience" pages.

```yaml
identity:   { first_name: Ada, last_name: Lovelace, email: ada@example.com, phone: "+1 555-0100" }
resume_path: /Users/you/Documents/resume.pdf
```

**2. Work history & education.** One block per job/school. Education entries take an
optional `workday_name`/`search_term` — Workday's school list often names a school
differently than you would, so this tells the tool exactly what to search and pick:

```yaml
education:
  - school: Example State University
    degree: Master's
    field: Computer Science
    end: 2027-06            # also used as your graduation date on question pages
    current: true
    search_term: Example State          # what to type into Workday's school search
    workday_name: Example State University   # the exact option to select
```

**3. Sensitive answers (visa, salary, EEO).** Set what applies to *you*; blanks are
flagged for manual entry, never guessed:

```yaml
sensitive:
  work_authorization: "Authorized to work in the US"   # or "US citizen", "Permanent resident", ...
  requires_sponsorship: "No"        # Yes / No
  gender: ""                        # EEO — blank = decline to answer
  race_ethnicity: ""                # blank = decline
  veteran_status: ""                # blank = decline
  disability_status: ""             # blank = decline
preferences:
  desired_salary: "120000"          # blank = flagged, not auto-filled
  earliest_start_date: "ASAP"
```

The tool answers visa/citizenship questions only from these fields — e.g. it will
**not** claim you're a citizen just because you're authorized to work.

**4. Common screening questions → `screening_rules.yaml`** (this file *is* in the
repo and is meant to be edited). It maps question keywords to a fixed answer:

```yaml
rules:
  - { match: [non-compete],  answer: "No" }
  - { match: [arbitration],  answer: "Yes" }   # change to "No" to decline arbitration
```

The shipped defaults are common but not universal. Open it once, change any answer
that doesn't fit you, or delete a rule so that question gets **flagged for you to
answer by hand** instead. No Python required.

**5. Free-text questions (optional LLM).** Anything not covered by the above can go
to an LLM resolver, grounded only in your profile. Enable it with
`export ANTHROPIC_API_KEY=...` (or point at a local Ollama model in
`agent_config.yaml`). Without a key, those questions are simply flagged.

**Then run it.** Every field shows up in a review table and the tool **stops before
Submit** — so you fill anything marked `FLAG`/`NEEDS FIX` directly in Chrome, then
submit yourself.

## Running

1. Quit Chrome completely (Cmd+Q, not just the window).
2. Launch Chrome with remote debugging (reuses your real profile):
   ```bash
   ./scripts/launch_chrome.sh
   ```
3. In that Chrome, sign into the Workday tenant and open the application page.
4. Fill it:
   ```bash
   ./venv/bin/python -m src.fill
   ```

```bash
./venv/bin/pytest   # CDP test auto-skips if no debug Chrome is running
```

By default the tool **stops before the final Submit** so you review everything
(`auto_submit: false` in `agent_config.yaml`). Flip it to `true` to submit
automatically — at your own risk.

## Status

Early but working: it connects to real Chrome, detects Workday fields, and fills
the application pages against live postings with a review report, halting at the
Review step for you to submit. See `DESIGN.md` and `TASKS.md`.

## Privacy

The browser automation runs locally and drives a session you're already logged
into. Your details live in a gitignored `profile.yaml` (and `accounts.yaml`,
`applications.yaml`) — none of these are tracked by git, so nothing personal ships
with the repo. If you point the question resolver at a hosted model, only the
free-text questions go out; everything else stays on your machine.
