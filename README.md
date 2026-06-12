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
- Free-text and screening questions go through a configurable LLM resolver — run
  it on a local model (Ollama) or a hosted one — and low-confidence answers are
  flagged rather than silently guessed.
- `auto_submit` in `agent_config.yaml` controls the last step: leave it off to
  stop before Submit and review, or turn it on to submit automatically.

## Setup

```bash
python3.13 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/playwright install chromium
```

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

## Status

Early but working: it connects to real Chrome, detects Workday fields, and fills
the "My Information" page against a live posting with a review report. Next up is
generating `profile.yaml` straight from a resume. See `DESIGN.md` and `TASKS.md`.

## Privacy

The browser automation runs locally and drives a session you're already logged
into. Your details live in a gitignored `profile.yaml`. If you point the question
resolver at a hosted model, only the free-text questions go out; everything else
stays on your machine.
