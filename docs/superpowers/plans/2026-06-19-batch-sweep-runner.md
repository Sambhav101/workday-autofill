# Batch-and-Sweep Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run each queued job in its own fresh tab, leave the tabs that need a human (`captcha`/`review`/`blocked`) open while closing the rest, and fire a cross-platform "N jobs need you" notification when the batch finishes — so an unattended run leaves a tidy set of tabs to sweep.

**Architecture:** Extract the macOS-only `_notify` from `lever.py` into a shared, cross-platform `src/ats/notify.py`. Add a pure `keeps_tab_open(status)` helper. Rework both run paths (`web/runner.py:_worker` and `ats.run_batch`) to open `ctx.new_page()` per job and keep/close it by outcome, then summarize + notify at the end.

**Tech Stack:** Python 3.14, Playwright (sync) over CDP, FastAPI/uvicorn (web), pytest, stdlib `winsound`/`subprocess`.

## Global Constraints

- Python 3.14 + `playwright>=1.50`; use the project venv (`./venv/bin/python`, `./venv/bin/pytest`). Never global Python.
- Git: no `Co-Authored-By:` lines. Work stays on branch `feat/batch-sweep-runner`.
- **No new dependencies** — notification uses stdlib only (`osascript`/`winsound`/`notify-send`), always best-effort (never raises).
- Keep-open set is exactly `{captcha, review, blocked}`; close `{submitted, skipped, error}`.
- `notify(title, message)` must never raise on any platform.
- `b.close()` on a CDP connection only disconnects — kept-open tabs persist in the real Chrome; do not add page cleanup that would close them.
- Driver/fill behavior is unchanged; this only changes the runner tab lifecycle + notification.

---

### Task 1: Cross-platform `notify` (extract from lever)

**Files:**
- Create: `src/ats/notify.py`
- Modify: `src/ats/lever.py` (remove local `_notify`; import + use `notify`)
- Modify: `src/ats/ashby.py` (drop `_notify` from the lever import; import + use `notify`)
- Test: `tests/test_ats_notify.py`

**Interfaces:**
- Produces: `notify(title: str, message: str) -> None` — best-effort desktop ping, never raises.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ats_notify.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.ats.notify as notify_mod
from src.ats.notify import notify


def test_notify_returns_none():
    assert notify("Title", "Message") is None


def test_notify_never_raises_when_backend_fails(monkeypatch):
    def boom(*a, **k):
        raise OSError("backend unavailable")
    monkeypatch.setattr(notify_mod.subprocess, "run", boom)
    # must swallow the error on every platform path that shells out
    notify("Title", "Message")


def test_notify_handles_quotes_in_text():
    # double quotes in the message must not break the osascript string build
    notify('a "quoted" title', 'msg with "quotes"')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_ats_notify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ats.notify'`

- [ ] **Step 3: Create `src/ats/notify.py`**

```python
# src/ats/notify.py
"""Best-effort, cross-platform desktop notification. Always a no-op on failure —
notifications are a nicety, never a reason to break a run."""
from __future__ import annotations

import subprocess
import sys


def notify(title: str, message: str) -> None:
    """Ping the user: macOS toast / Windows beep / Linux notify-send. Never raises."""
    try:
        if sys.platform == "darwin":
            safe = lambda s: s.replace('"', "'")
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{safe(message)}" with title "{safe(title)}" '
                 f'sound name "Glass"'],
                check=False, capture_output=True, timeout=5)
        elif sys.platform == "win32":
            import winsound  # stdlib on Windows
            winsound.MessageBeep()
        else:  # linux / other
            subprocess.run(["notify-send", title, message],
                           check=False, capture_output=True, timeout=5)
    except Exception:  # noqa: BLE001
        pass
```

- [ ] **Step 4: Refactor `src/ats/lever.py` onto it**

Delete the local `_notify` function (currently near lines 299-318). Add an import near the top with the other `from .` imports (e.g. after `from .captcha import has_captcha`):

```python
from .notify import notify
```

In `lever.py:main`, change the captcha ping call:

```python
    if result["status"] == "captcha":
        notify("Lever: CAPTCHA — action needed",
               f"{result.get('company', 'job')} filled. Solve the captcha and submit.")
```

- [ ] **Step 5: Refactor `src/ats/ashby.py` onto it**

Change the import line (currently `from .lever import full_name, current_company, _notify`) to drop `_notify`:

```python
from .lever import full_name, current_company
from .notify import notify
```

In `ashby.py:main`, change the captcha ping call:

```python
    if result["status"] == "captcha":
        notify("Ashby: CAPTCHA — action needed",
               f"{result.get('company', 'job')} filled. Solve the captcha and submit.")
```

- [ ] **Step 6: Confirm no leftover `_notify` references**

Run: `grep -rn "_notify" src | grep -v __pycache__`
Expected: NO matches.

- [ ] **Step 7: Run tests**

Run: `./venv/bin/pytest tests/test_ats_notify.py -v` → Expected: PASS (3 passed)
Run: `./venv/bin/python -c "import src.ats.lever, src.ats.ashby, src.ats.notify; print('import ok')"` → Expected: `import ok`
Run: `./venv/bin/pytest -q` → Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/ats/notify.py src/ats/lever.py src/ats/ashby.py tests/test_ats_notify.py
git commit -m "refactor(ats): cross-platform notify() shared by drivers"
```

---

### Task 2: `keeps_tab_open` decision helper

**Files:**
- Modify: `src/ats/__init__.py` (add `_KEEP_OPEN` + `keeps_tab_open`)
- Test: `tests/test_keeps_tab_open.py`

**Interfaces:**
- Consumes: `ApplyStatus` (already imported in `__init__.py`).
- Produces: `keeps_tab_open(status) -> bool` — True for `captcha`/`review`/`blocked`; accepts an `ApplyStatus` or its string value.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_keeps_tab_open.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats import keeps_tab_open
from src.ats.base import ApplyStatus


def test_keep_open_statuses():
    for s in ["captcha", "review", "blocked"]:
        assert keeps_tab_open(s) is True


def test_close_statuses():
    for s in ["submitted", "skipped", "error"]:
        assert keeps_tab_open(s) is False


def test_accepts_enum_member():
    assert keeps_tab_open(ApplyStatus.CAPTCHA) is True
    assert keeps_tab_open(ApplyStatus.SUBMITTED) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_keeps_tab_open.py -v`
Expected: FAIL with `ImportError: cannot import name 'keeps_tab_open' from 'src.ats'`

- [ ] **Step 3: Add to `src/ats/__init__.py`** (after the `dispatch` function, before `run_batch`)

```python
_KEEP_OPEN = {ApplyStatus.CAPTCHA, ApplyStatus.REVIEW, ApplyStatus.BLOCKED}


def keeps_tab_open(status) -> bool:
    """True if a job's outcome needs the human, so its tab should stay open for review."""
    return ApplyStatus(status) in _KEEP_OPEN
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_keeps_tab_open.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ats/__init__.py tests/test_keeps_tab_open.py
git commit -m "feat(ats): keeps_tab_open status helper"
```

---

### Task 3: Web runner — fresh tab per job, keep/close, end summary + notify

**Files:**
- Modify: `src/web/runner.py` (rewrite `_worker`, ~lines 57-99)
- Test: static checks + live (browser); the keep/close decision is unit-tested via Task 2.

**Interfaces:**
- Consumes: `dispatch`, `keeps_tab_open` (from `..ats`); `notify` (from `..ats.notify`).
- Produces: `run_queue` behavior — one tab per job; `{captcha,review,blocked}` tabs kept open; `done` event extended with `needs_you` + `submitted` counts; end-of-run `notify`.

- [ ] **Step 1: Replace the `_worker` function**

Replace the entire current `_worker` (from `def _worker():` through the `thread = threading.Thread(...)` line is unchanged; only the function body changes) with:

```python
    def _worker():
        global _running, _stop_flag
        from ..ats import dispatch, keeps_tab_open
        from ..ats.notify import notify
        needs_you = 0
        submitted = 0
        try:
            pw = sync_playwright().start()
            b = browser.connect(pw)
            ctx = b.contexts[0] if b.contexts else None
            if ctx is None:
                _emit("error", {"message": "No browser context available"})
                return

            while not _stop_flag:
                queued = Q.get_queued()
                if not queued:
                    break

                job = queued[0]
                url = job["url"]
                Q.update_status(url, "running")
                _emit("status", {"url": url, "status": "running"})

                page = ctx.new_page()
                try:
                    result = dispatch(page, url, auto_submit=auto_submit).to_dict()
                    status = result.get("status", "error")
                    reason = result.get("reason", "")
                    Q.update_status(url, status, reason)
                    _emit("result", {
                        "url": url, "status": status, "reason": reason,
                        "title": result.get("title", ""), "tenant": result.get("tenant", ""),
                    })
                except Exception as e:
                    status = "error"
                    Q.update_status(url, "error", str(e))
                    _emit("result", {"url": url, "status": "error", "reason": str(e)[:200]})

                if status == "submitted":
                    submitted += 1
                if keeps_tab_open(status):
                    needs_you += 1
                else:
                    try:
                        page.close()
                    except Exception:  # noqa: BLE001
                        pass

            print(f"[autofill] Queue finished — {needs_you} need you, {submitted} submitted",
                  flush=True)
            notify("Autofill finished",
                   f"{needs_you} job(s) need you — solve captcha / review & submit"
                   if needs_you else "All queued jobs processed.")
            _emit("done", {"message": "All jobs processed",
                           "needs_you": needs_you, "submitted": submitted})
            b.close()
            pw.stop()
        except Exception as e:
            _emit("error", {"message": str(e)[:200]})
        finally:
            _running = False
            _emit("stopped", {})
```

- [ ] **Step 2: Static checks (live run is the controller's)**

Run: `./venv/bin/python -c "import ast; ast.parse(open('src/web/runner.py').read()); print('syntax ok')"`
Run: `./venv/bin/python -c "import src.web.runner; print('import ok')"`
Run: `./venv/bin/pytest -q` → Expected: all pass (no test drives the browser thread; this confirms no import/syntax regressions).
Do NOT attempt to drive a live browser — the controller runs the live check.

- [ ] **Step 3: Commit**

```bash
git add src/web/runner.py
git commit -m "feat(web): one tab per job; keep captcha/review/blocked open; notify on finish"
```

- [ ] **Step 4: Live verification (controller — needs Chrome on CDP + the web UI)**

Launch Chrome (`scripts/launch_chrome.sh`), start the web UI (`python -m src.web`), queue 2-3 single-page jobs including at least one captcha form and one clean form, click Run. Confirm: the captcha/review tab(s) stay open in Chrome, the clean job's tab closes, the UI `done` event shows `needs_you`/`submitted` counts, and the finish notification fires (beep on Windows / toast on macOS).

---

### Task 4: `run_batch` — same tab lifecycle + notify

**Files:**
- Modify: `src/ats/__init__.py` (`run_batch`, ~lines 44-100)
- Test: static checks + live (browser).

**Interfaces:**
- Consumes: `dispatch`, `keeps_tab_open`, `ApplyResult`, `ApplyStatus` (same module); `notify` (from `.notify`).
- Produces: `run_batch` — one tab per URL; `{captcha,review,blocked}` tabs kept open; end-of-run `notify` + the existing rich summary/`report.yaml`.

- [ ] **Step 1: Rework the per-job loop and add the finish notify**

In `run_batch`, replace the browser/loop body. The current loop uses one `page = browser.find_any_tab(b)` and `dispatch(page, url)`. Change to a per-URL `ctx.new_page()` with keep/close, and notify at the end. Replace from `with sync_playwright() as pw:` through `b.close()` with:

```python
    with sync_playwright() as pw:
        b = browser.connect(pw)
        ctx = b.contexts[0] if b.contexts else None
        if ctx is None:
            console.print("[red]No browser context available.[/red]")
            return results

        needs_you = 0
        for i, url in enumerate(urls, 1):
            console.rule(f"[bold]Job {i}/{len(urls)}[/bold]")
            page = ctx.new_page()
            try:
                result = dispatch(page, url, auto_submit=auto_submit)
            except Exception as e:  # noqa: BLE001
                result = ApplyResult(ApplyStatus.ERROR, str(e), {"url": url})
            results.append(result)
            job = result.job
            line = f"{job.get('title', '?')} @ {job.get('tenant', '?')} — {result.status.value}"
            color = {"submitted": "green", "review": "cyan", "skipped": "dim",
                     "captcha": "magenta", "blocked": "yellow", "error": "red"}.get(
                         result.status.value, "white")
            console.print(f"[{color}]{line}: {result.reason}[/{color}]")
            report_path.write_text(yaml.safe_dump(
                [r.to_dict() for r in results], default_flow_style=False, sort_keys=False))
            if keeps_tab_open(result.status):
                needs_you += 1
            else:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass

        b.close()

    from .notify import notify
    notify("Autofill finished",
           f"{needs_you} job(s) need you — solve captcha / review & submit"
           if needs_you else "All jobs processed.")
```

Leave the "Batch Summary" table block and the final `return results` unchanged (they run after the `with` block).

- [ ] **Step 2: Static checks**

Run: `./venv/bin/python -c "import ast; ast.parse(open('src/ats/__init__.py').read()); print('syntax ok')"`
Run: `./venv/bin/python -c "from src.ats import run_batch, keeps_tab_open; print('import ok')"`
Run: `./venv/bin/pytest -q` → Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add src/ats/__init__.py
git commit -m "feat(ats): run_batch opens a tab per job, keeps needs-you tabs open, notifies"
```

- [ ] **Step 4: Live verification (controller)**

`./venv/bin/python -c "from src.ats import run_batch; run_batch([<one lever/ashby url>], auto_submit=False)"` against a live Chrome — confirm the captcha/review tab stays open, the summary prints, and the finish notification fires.

---

## Self-Review

**Spec coverage:**
- Fresh tab per job → Tasks 3 (web) + 4 (run_batch), `ctx.new_page()`. ✓
- Keep `captcha/review/blocked` open, close the rest → Task 2 (`keeps_tab_open`) used by 3 & 4. ✓
- End state: kept tabs persist (`b.close()` disconnects only) → Tasks 3 & 4, Global Constraints. ✓
- Cross-platform dependency-free notify → Task 1 (`notify.py`). ✓
- Batch-done summary + notify on both paths → Tasks 3 & 4. ✓
- `done` event extended with counts → Task 3. ✓
- Both web runner and run_batch → Tasks 3 & 4. ✓
- Testing: offline units (Tasks 1-2) + live (Tasks 3-4). ✓
- Out of scope (parallel filling, UI styling, Windows toast) → none added. ✓

**Placeholder scan:** No TBD/TODO; every code step is complete; live-verification steps are explicit controller instructions, not code placeholders. ✓

**Type consistency:** `notify(title, message)` signature identical across `notify.py`, lever, ashby, runner, run_batch. `keeps_tab_open(status)` accepts enum/string and is used identically in Tasks 3 & 4. `result.status` is an `ApplyStatus` in `run_batch` (passed directly to `keeps_tab_open`) and a string in the runner (`status` from `.to_dict()`) — `keeps_tab_open` handles both via `ApplyStatus(status)`. ✓
