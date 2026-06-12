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

- **Common safe questions** (over 18, willing to do a background check, conflict-of-
  interest, "have you worked here before") use keyword rules with fixed answers.
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
