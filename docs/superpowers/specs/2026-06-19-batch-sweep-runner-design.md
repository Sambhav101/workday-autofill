# Batch-and-Sweep Runner — Design Doc

**Date:** 2026-06-19
**Status:** Approved — ready for implementation plan

## Context

The goal is an unattended batch run: queue many job links, let it fill them while you
do other work (on a Windows box), then jump in at the end to solve captchas and submit.

Today this does not work, because both run paths **reuse a single tab**:

- `src/web/runner.py:_worker` — `page = browser.find_any_tab(b)` once, then
  `dispatch(page, url)` per job; the driver navigates that one page.
- `src/ats/__init__.py:run_batch` — same: one `find_any_tab` page, `dispatch` per URL.

So when a job stops at a captcha (most Lever/Ashby forms) or review, the **next job
navigates that filled form away** — by the time you "jump in at the end," it's gone.
You'd have to re-run captcha jobs one at a time.

The drivers already return the right signal: `ApplyStatus` is
`submitted / review / blocked / captcha / skipped / error`, and the single-page drivers
stop (don't submit) on `captcha`/`review`. The missing piece is the runner's tab
lifecycle.

## Goals

- Each job runs in its **own fresh tab**.
- Tabs for jobs that need the human (`captcha`, `review`, `blocked`) stay **open**;
  auto-completed tabs (`submitted`, `skipped`, `error`) **close**.
- End state: the real Chrome holds one open tab per job-that-needs-you, ready to sweep.
- A cross-platform, dependency-free "batch done — N need you" notification (works on
  the Windows run box).
- Same behavior for the web runner and the CLI/agent `run_batch`.

## Non-goals / out of scope

- True parallel filling (multiple tabs filling at once) — decided against (sync
  Playwright, thread-safety, races on shared login; low ROI since the human-review step
  is serial anyway).
- A rich Windows toast popup — chose an audible beep + console + web UI instead.
- Web UI status-dot styling for `captcha`/`review`/`blocked` (tracked in #8).
- Changing any driver's fill/submit behavior.

## Architecture

### Component 1 — tab-keep decision (pure)

A small pure helper, so the lifecycle rule is testable and shared by both run paths:

```python
# src/ats/__init__.py (or alongside dispatch)
_KEEP_OPEN = {ApplyStatus.CAPTCHA, ApplyStatus.REVIEW, ApplyStatus.BLOCKED}

def keeps_tab_open(status) -> bool:
    """True if a job's outcome needs the human, so its tab should stay open."""
    return ApplyStatus(status) in _KEEP_OPEN
```

Accepts either an `ApplyStatus` or its string value (coerces via `ApplyStatus(status)`).

### Component 2 — cross-platform notification (`src/ats/notify.py`, new)

Extract the existing macOS-only `_notify` from `src/ats/lever.py` into a shared,
cross-platform, best-effort `notify(title, message)`:

- **macOS** → `osascript` toast with sound (the current implementation).
- **Windows** → `winsound.MessageBeep()` (audible ping; standard library, no deps).
- **Linux** → `notify-send` if on PATH.
- Always wrapped so it **never raises** (notification is best-effort).

`lever.py` and `ashby.py` drop their `_notify` import-from-lever / local copy and import
`from .notify import notify`. Their CLI `main()` captcha ping calls `notify(...)`
unchanged in spirit.

### Component 3 — per-job tab lifecycle in the runner

`src/web/runner.py:_worker` — replace the single reused page with a fresh tab per job:

```python
ctx = b.contexts[0] if b.contexts else None
if ctx is None:
    _emit("error", {"message": "No browser context available"}); return
...
for each queued job:
    page = ctx.new_page()
    try:
        result = dispatch(page, url, auto_submit=auto_submit).to_dict()
        status = result.get("status", "error")
        Q.update_status(url, status, result.get("reason", ""))
        _emit("result", {...})            # unchanged event shape
    except Exception as e:
        status = "error"
        Q.update_status(url, "error", str(e)); _emit("result", {...})
    if not keeps_tab_open(status):
        page.close()
```

At the end (queue drained or stopped): count jobs whose status is in `_KEEP_OPEN`,
emit the existing `done` event **extended with `{needs_you: N, submitted: M}`**, print a
console summary, and call `notify("Autofill done", f"{N} job(s) need you — solve captcha / review & submit")`.
`b.close()` still runs — on a CDP connection it only disconnects, leaving the real
Chrome and the kept-open tabs intact.

### Component 4 — same lifecycle in `run_batch`

`src/ats/__init__.py:run_batch` — apply the identical per-job `new_page()` +
`keeps_tab_open` close logic, and the same end-of-run `notify(...)` + summary. Its rich
table/`report.yaml` reporting stays.

## Data flow

```
queue/CLI urls
  └─ for each url:
       ctx.new_page() ─▶ dispatch(page, url) ─▶ driver fills (navigates this tab)
            │
            ├─ submitted/skipped/error ─▶ page.close()
            └─ captcha/review/blocked  ─▶ leave tab open
  └─ end: count needs-you ─▶ web 'done'{needs_you,submitted} + console + notify() beep
  (real Chrome keeps one tab per needs-you job; you sweep them)
```

## Failure modes / risks

- **Many open tabs on a large captcha-heavy batch** — expected and desired (one per job
  needing you). Not mitigated; it's the feature.
- **`b.contexts` empty** — guarded with an explicit error emit / early return.
- **`new_page()` focus-stealing** — pre-existing for any browser automation; the
  dedicated Chrome instance keeps it off your normal browsing. Park it on another
  virtual desktop.
- **A driver that navigates the *current* tab instead of the one passed** — both drivers
  navigate the `page` they're given (`apply_one(..., page=page)` / `WorkdayDriver`
  `page.goto`), so a fresh `new_page()` is the tab they act on. Verified live.
- **Notification failure** (no `osascript`/`winsound`/`notify-send`) — best-effort
  try/except, never breaks the run.

## Testing

- **Unit (offline):**
  - `keeps_tab_open` for all six statuses (True for captcha/review/blocked; False
    otherwise), accepting both enum and string.
  - `notify(...)` is best-effort: monkeypatch the platform call / assert it never raises
    on any `sys.platform`.
  - Lever/ashby still import `notify` and their tests stay green after the extraction.
- **Live (manual, before merge):** queue 2–3 single-page jobs (at least one captcha
  form + one clean form); Run from the web UI; confirm the captcha/review tab(s) stay
  open, the clean job's tab closes, the `done` summary shows the right counts, and the
  finish notification fires.

## Rollout

1. Extract `src/ats/notify.py`; refactor lever/ashby onto it (tests stay green).
2. Add `keeps_tab_open` + `_KEEP_OPEN`.
3. Rework `web/runner.py:_worker` (fresh tab per job, keep/close, end summary + notify).
4. Apply the same lifecycle + notify to `ats.run_batch`.
5. Live-verify a mixed batch from the web UI.
6. Merge.

## Open questions

None — keep-open set (`captcha`/`review`/`blocked`), notification approach (sound +
console + web UI, no new deps), and scope (web runner + `run_batch`) are resolved.
