# workday-autofill

Fills Workday job applications by driving your **real, logged-in Chrome**, then
**stops at the final Submit** so you review and submit yourself. See `DESIGN.md`.

## Setup

```bash
python3.13 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/playwright install chromium
```

## Running

1. **Quit Chrome completely** (Cmd+Q — not just close the window).
2. Launch Chrome with remote debugging (reuses your real profile/logins):
   ```bash
   ./scripts/launch_chrome.sh
   ```
3. In that Chrome, log into the Workday tenant and open the job application page.
4. Run the filler (Milestone 2+):
   ```bash
   ./venv/bin/python -m src.fill   # fills, pauses before Submit
   ```

## Tests

```bash
./venv/bin/pytest        # CDP test auto-skips if no debug Chrome is running
```

## Status

Milestone 0 (scaffold) done. Next: `profile.yaml` from resume, then the
"My Information" prototype against the Adobe ML Engineer posting (see `TASKS.md`).
