# ATSDriver Interface + Unified Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a typed `ATSDriver` contract + `ApplyResult` and a single `dispatch`/`run_batch` that all three apply-consumers route through, wrapping the existing Workday and Lever code unchanged — which also fixes the live bug where web-queued / batched Lever URLs are fed to the Workday driver.

**Architecture:** A new `src/ats/base.py` defines `ApplyStatus`, `ApplyResult`, and the `ATSDriver` Protocol. `WorkdayDriver` (new `src/ats/workday.py`) and `LeverDriver` (added to `src/ats/lever.py`) are thin wrappers over the untouched `apply._run_one` and `lever.apply_one`. `src/ats/__init__.py` holds the driver registry, `driver_for`, `dispatch`, and a driver-agnostic `run_batch`. Consumers (`agent/tools.py`, `web/runner.py`, `apply.py` CLI) call the dispatcher.

**Tech Stack:** Python 3.14, Playwright (sync) over CDP, pytest, dataclasses + enum, rich, PyYAML.

## Global Constraints

- Python 3.14 + `playwright>=1.50`; use the project venv (`./venv/bin/python`, `./venv/bin/pytest`). Never global Python.
- Git: no `Co-Authored-By:` lines. Work stays on branch `feat/ats-driver-interface`.
- **Do not modify Workday internals** — `apply._run_one`, `apply.detect`, `apply.FILLERS`, `apply._check_required_fields`, signup, etc. stay byte-for-byte. Workday is wrapped, not rewritten.
- **`ApplyStatus` is `str, Enum`** with values exactly: `submitted`, `review`, `blocked`, `captcha`, `skipped`, `error`. `ApplyResult.to_dict()` must emit those exact strings (back-compat: `applications.yaml`, `report.yaml`, web events, agent tools all read flat dicts with string statuses).
- **Drivers own navigation:** `ATSDriver.apply(page, url, *, auto_submit)` does its own `goto`. Consumers stop pre-navigating.
- `ApplyResult.to_dict()` shape is exactly `{"status": <str>, "reason": <str>, **job}` — the same flat shape both drivers return today.

---

### Task 1: The contract — `ApplyStatus`, `ApplyResult`, `ATSDriver`

**Files:**
- Create: `src/ats/base.py`
- Test: `tests/test_ats_base.py`

**Interfaces:**
- Produces:
  - `class ApplyStatus(str, Enum)` — `SUBMITTED="submitted"`, `REVIEW="review"`, `BLOCKED="blocked"`, `CAPTCHA="captcha"`, `SKIPPED="skipped"`, `ERROR="error"`.
  - `@dataclass(frozen=True) class ApplyResult` with `status: ApplyStatus`, `reason: str`, `job: dict`; methods `to_dict() -> dict` and classmethod `from_dict(d: dict) -> ApplyResult`.
  - `class ATSDriver(Protocol)` with `name: str` and `apply(self, page, url: str, *, auto_submit: bool) -> ApplyResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ats_base.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats.base import ApplyStatus, ApplyResult


def test_status_vocabulary():
    assert [s.value for s in ApplyStatus] == [
        "submitted", "review", "blocked", "captcha", "skipped", "error"]


def test_to_dict_stringifies_status_and_spreads_job():
    r = ApplyResult(ApplyStatus.SUBMITTED, "ok", {"title": "ML Eng", "tenant": "hive"})
    assert r.to_dict() == {
        "status": "submitted", "reason": "ok", "title": "ML Eng", "tenant": "hive"}


def test_from_dict_round_trip_preserves_all_keys():
    flat = {"status": "review", "reason": "stopped", "title": "X", "tenant": "y", "job_id": "1"}
    r = ApplyResult.from_dict(flat)
    assert r.status is ApplyStatus.REVIEW
    assert r.reason == "stopped"
    assert r.job == {"title": "X", "tenant": "y", "job_id": "1"}
    assert r.to_dict() == flat


def test_from_dict_coerces_every_driver_status():
    for s in ["submitted", "review", "blocked", "captcha", "skipped", "error"]:
        assert ApplyResult.from_dict({"status": s, "reason": ""}).status == ApplyStatus(s)


def test_from_dict_defaults_when_missing():
    r = ApplyResult.from_dict({"title": "only-meta"})
    assert r.status is ApplyStatus.ERROR
    assert r.reason == ""
    assert r.job == {"title": "only-meta"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_ats_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ats.base'`

- [ ] **Step 3: Write the implementation**

```python
# src/ats/base.py
"""Shared ATS driver contract: the result type every driver returns and the
Protocol every driver implements."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class ApplyStatus(str, Enum):
    SUBMITTED = "submitted"
    REVIEW = "review"
    BLOCKED = "blocked"
    CAPTCHA = "captcha"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of applying to one job. `job` carries metadata (title/tenant/url/...)."""
    status: ApplyStatus
    reason: str
    job: dict

    def to_dict(self) -> dict:
        """Flat back-compat shape: {status: <str>, reason, **job}."""
        return {"status": self.status.value, "reason": self.reason, **self.job}

    @classmethod
    def from_dict(cls, d: dict) -> "ApplyResult":
        """Build from a legacy {status, reason, **job} dict."""
        d = dict(d)
        status = d.pop("status", "error")
        reason = d.pop("reason", "")
        return cls(ApplyStatus(status), reason, d)


@runtime_checkable
class ATSDriver(Protocol):
    name: str

    def apply(self, page, url: str, *, auto_submit: bool) -> ApplyResult:
        """Navigate to `url` and fill/submit one application. Driver owns navigation."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_ats_base.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ats/base.py tests/test_ats_base.py
git commit -m "feat(ats): ApplyStatus/ApplyResult/ATSDriver contract (#2)"
```

---

### Task 2: Drivers — `WorkdayDriver` and `LeverDriver`

**Files:**
- Create: `src/ats/workday.py`
- Modify: `src/ats/lever.py` (append `LeverDriver`; do not change existing functions)
- Test: `tests/test_ats_drivers.py`

**Interfaces:**
- Consumes: `ApplyResult`, `ApplyStatus` from `src/ats/base.py` (Task 1); `apply._run_one(page, *, auto_submit)` and `lever.apply_one(url, *, auto_submit, page)` (both return `{status, reason, **job}` dicts, unchanged).
- Produces:
  - `class WorkdayDriver` with `name = "workday"` and `apply(self, page, url, *, auto_submit) -> ApplyResult`.
  - `class LeverDriver` with `name = "lever"` and `apply(self, page, url, *, auto_submit) -> ApplyResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ats_drivers.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats.base import ApplyResult, ApplyStatus
from src.ats.workday import WorkdayDriver
from src.ats.lever import LeverDriver


class FakePage:
    def __init__(self):
        self.goto_url = None
    def goto(self, url):
        self.goto_url = url
    def wait_for_timeout(self, ms):
        pass


def test_driver_names():
    assert WorkdayDriver().name == "workday"
    assert LeverDriver().name == "lever"


def test_workday_driver_navigates_then_wraps_result(monkeypatch):
    import src.apply as apply_mod
    captured = {}
    def fake_run_one(page, *, auto_submit):
        captured["auto_submit"] = auto_submit
        return {"status": "review", "reason": "stopped", "title": "WD Job", "tenant": "acme"}
    monkeypatch.setattr(apply_mod, "_run_one", fake_run_one)

    page = FakePage()
    result = WorkdayDriver().apply(page, "https://acme.wd5.myworkdayjobs.com/job/x", auto_submit=True)
    assert page.goto_url == "https://acme.wd5.myworkdayjobs.com/job/x"
    assert captured["auto_submit"] is True
    assert isinstance(result, ApplyResult)
    assert result.status is ApplyStatus.REVIEW
    assert result.job["title"] == "WD Job"


def test_lever_driver_delegates_and_wraps(monkeypatch):
    import src.ats.lever as lever_mod
    captured = {}
    def fake_apply_one(url=None, *, auto_submit=False, page=None):
        captured.update(url=url, auto_submit=auto_submit, page=page)
        return {"status": "captcha", "reason": "solve it", "company": "hive"}
    monkeypatch.setattr(lever_mod, "apply_one", fake_apply_one)

    page = FakePage()
    result = LeverDriver().apply(page, "https://jobs.lever.co/hive/abc", auto_submit=False)
    assert captured == {"url": "https://jobs.lever.co/hive/abc", "auto_submit": False, "page": page}
    assert result.status is ApplyStatus.CAPTCHA
    assert result.job["company"] == "hive"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_ats_drivers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ats.workday'`

- [ ] **Step 3: Write `src/ats/workday.py`**

```python
# src/ats/workday.py
"""Workday driver: wraps the existing multi-page wizard runner in apply.py.
Navigation + the apply-button/sign-in pre-flow already live inside _run_one."""
from __future__ import annotations

from .base import ApplyResult, ATSDriver


class WorkdayDriver:
    name = "workday"

    def apply(self, page, url: str, *, auto_submit: bool) -> ApplyResult:
        from ..apply import _run_one  # lazy: avoids import cycle (apply ↔ ats)
        page.goto(url)
        page.wait_for_timeout(5000)
        return ApplyResult.from_dict(_run_one(page, auto_submit=auto_submit))
```

- [ ] **Step 4: Append `LeverDriver` to `src/ats/lever.py`**

Add at the end of the file (after `_notify`), and add the import near the other `from .` imports at the top:

```python
from .base import ApplyResult
```

```python
class LeverDriver:
    name = "lever"

    def apply(self, page, url: str, *, auto_submit: bool) -> ApplyResult:
        return ApplyResult.from_dict(apply_one(url, auto_submit=auto_submit, page=page))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_ats_drivers.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/ats/workday.py src/ats/lever.py tests/test_ats_drivers.py
git commit -m "feat(ats): WorkdayDriver + LeverDriver wrapping existing runners (#2)"
```

---

### Task 3: Registry, `driver_for`, `dispatch`, `run_batch`

**Files:**
- Modify: `src/ats/__init__.py`
- Test: `tests/test_ats_dispatch.py`

**Interfaces:**
- Consumes: `detect_ats` (existing in `__init__.py`); `WorkdayDriver`, `LeverDriver` (Task 2); `ApplyResult`, `ApplyStatus` (Task 1).
- Produces:
  - `driver_for(url: str) -> ATSDriver | None`
  - `dispatch(page, url: str, *, auto_submit: bool) -> ApplyResult` (unknown host → `ApplyResult(ERROR, ...)`, never raises for routing).
  - `run_batch(urls: list[str], *, auto_submit: bool = True) -> list[ApplyResult]` (one shared CDP browser; `dispatch` per URL; rich summary table + `report.yaml`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ats_dispatch.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats import driver_for, dispatch
from src.ats.base import ApplyStatus
from src.ats.workday import WorkdayDriver
from src.ats.lever import LeverDriver


class FakePage:
    def goto(self, url):
        pass
    def wait_for_timeout(self, ms):
        pass


def test_driver_for_maps_by_host():
    assert isinstance(driver_for("https://acme.wd5.myworkdayjobs.com/job/x"), WorkdayDriver)
    assert isinstance(driver_for("https://jobs.lever.co/hive/abc"), LeverDriver)
    assert driver_for("https://boards.greenhouse.io/foo/jobs/1") is None


def test_dispatch_unknown_host_returns_error_without_raising():
    r = dispatch(FakePage(), "https://example.com/job", auto_submit=False)
    assert r.status is ApplyStatus.ERROR
    assert "example.com" in r.reason or "No driver" in r.reason


def test_dispatch_routes_to_lever(monkeypatch):
    import src.ats.lever as lever_mod
    monkeypatch.setattr(lever_mod, "apply_one",
                        lambda url=None, *, auto_submit=False, page=None:
                        {"status": "submitted", "reason": "done", "company": "hive"})
    r = dispatch(FakePage(), "https://jobs.lever.co/hive/abc", auto_submit=True)
    assert r.status is ApplyStatus.SUBMITTED
    assert r.job["company"] == "hive"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_ats_dispatch.py -v`
Expected: FAIL with `ImportError: cannot import name 'driver_for' from 'src.ats'`

- [ ] **Step 3: Extend `src/ats/__init__.py`**

Append after the existing `detect_ats` function:

```python
from .base import ApplyResult, ApplyStatus, ATSDriver
from .workday import WorkdayDriver
from .lever import LeverDriver

_REGISTRY: dict[str, ATSDriver] = {
    "workday": WorkdayDriver(),
    "lever": LeverDriver(),
}


def driver_for(url: str) -> ATSDriver | None:
    """Return the driver for a job URL, or None if no ATS matches."""
    return _REGISTRY.get(detect_ats(url))


def dispatch(page, url: str, *, auto_submit: bool) -> ApplyResult:
    """Route one job URL to its driver. Unknown host → ERROR result (no raise)."""
    driver = driver_for(url)
    if driver is None:
        return ApplyResult(ApplyStatus.ERROR, f"No driver for URL: {url}", {"url": url})
    return driver.apply(page, url, auto_submit=auto_submit)


def run_batch(urls: list[str], *, auto_submit: bool = True) -> list[ApplyResult]:
    """Apply to multiple jobs across any supported ATS. Errors are logged, not raised."""
    from pathlib import Path
    import yaml
    from playwright.sync_api import sync_playwright
    from rich.console import Console
    from rich.table import Table
    from .. import browser

    console = Console()
    report_path = Path(__file__).resolve().parent.parent.parent / "report.yaml"
    results: list[ApplyResult] = []

    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_any_tab(b)
        if not page:
            console.print("[red]No Chrome tab available.[/red]")
            return results

        for i, url in enumerate(urls, 1):
            console.rule(f"[bold]Job {i}/{len(urls)}[/bold]")
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

        b.close()

    console.rule("[bold]Batch Summary[/bold]")
    table = Table()
    for col in ("Job", "Company", "Status", "Reason"):
        table.add_column(col)
    for r in results:
        color = {"submitted": "green", "review": "cyan", "skipped": "dim",
                 "captcha": "magenta", "blocked": "yellow", "error": "red"}.get(
                     r.status.value, "white")
        table.add_row(r.job.get("title", "?")[:40], r.job.get("tenant", "?"),
                      f"[{color}]{r.status.value}[/{color}]", r.reason[:60])
    console.print(table)
    console.print(f"\nFull report saved to [bold]{report_path}[/bold]")
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_ats_dispatch.py -v`
Expected: PASS (3 passed). `run_batch` is browser-coupled and is verified live in Task 5, not unit-tested.

- [ ] **Step 5: Run the full suite (no regressions from the new imports)**

Run: `./venv/bin/pytest -q`
Expected: all pass (the new `_REGISTRY` import wiring must not break existing collection).

- [ ] **Step 6: Commit**

```bash
git add src/ats/__init__.py tests/test_ats_dispatch.py
git commit -m "feat(ats): registry + dispatch + driver-agnostic run_batch (#2)"
```

---

### Task 4: Route the agent + web consumers through dispatch

**Files:**
- Modify: `src/agent/tools.py` (`_apply_to_job` lines 41-51, `_apply_batch` lines 54-56)
- Modify: `src/web/runner.py` (the `_worker` per-job block, ~lines 73-89; and the top import line 12)
- Test: extend `tests/test_ats_dispatch.py`

**Interfaces:**
- Consumes: `dispatch`, `run_batch` (Task 3).
- Produces: `_apply_to_job(url) -> dict` and `_apply_batch(urls) -> list[dict]` now ATS-agnostic; the web worker processes any supported ATS.

- [ ] **Step 1: Add a routing-contract test**

```python
# append to tests/test_ats_dispatch.py
def test_dispatch_routes_to_workday(monkeypatch):
    import src.apply as apply_mod
    monkeypatch.setattr(apply_mod, "_run_one",
                        lambda page, *, auto_submit:
                        {"status": "review", "reason": "ok", "tenant": "acme"})
    r = dispatch(FakePage(), "https://acme.wd5.myworkdayjobs.com/job/x", auto_submit=False)
    assert r.status is ApplyStatus.REVIEW
    assert r.job["tenant"] == "acme"
```

- [ ] **Step 2: Run it to confirm it passes (guards the contract these consumers rely on)**

Run: `./venv/bin/pytest tests/test_ats_dispatch.py::test_dispatch_routes_to_workday -v`
Expected: PASS

- [ ] **Step 3: Replace `_apply_to_job` and `_apply_batch` in `src/agent/tools.py`**

Replace the whole current bodies (lines 41-56) with:

```python
def _apply_to_job(url: str) -> dict:
    from ..ats import dispatch
    page = _get_page()
    return dispatch(page, url, auto_submit=True).to_dict()


def _apply_batch(urls: list[str]) -> list[dict]:
    from ..ats import run_batch
    return [r.to_dict() for r in run_batch(urls, auto_submit=True)]
```

- [ ] **Step 4: Route the web worker in `src/web/runner.py`**

Delete the top-level import on line 12 (`from ..apply import _run_one`). In `_worker`, replace the per-job try-block body that currently reads:

```python
                try:
                    page.goto(url)
                    page.wait_for_timeout(5000)
                    result = _run_one(page, auto_submit=auto_submit)
                    status = result.get("status", "error")
```

with (the driver now navigates — drop the goto/wait):

```python
                try:
                    from ..ats import dispatch
                    result = dispatch(page, url, auto_submit=auto_submit).to_dict()
                    status = result.get("status", "error")
```

Leave the rest of the block (reason/title/`Q.update_status`/`_emit`) unchanged.

- [ ] **Step 5: Verify imports resolve and full suite passes**

Run: `./venv/bin/python -c "import src.agent.tools, src.web.runner; print('import ok')"`
Run: `./venv/bin/pytest -q`
Expected: `import ok`; all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/agent/tools.py src/web/runner.py tests/test_ats_dispatch.py
git commit -m "feat(ats): route agent + web consumers through dispatch (#2)"
```

---

### Task 5: Re-point the `apply.py` CLI through dispatch

**Files:**
- Modify: `src/apply.py` (`run_batch` lines 430-480, `main` lines 483-496)
- Test: live (browser); plus full unit suite for no-regression

**Interfaces:**
- Consumes: `dispatch`, `run_batch` (Task 3).
- Produces: `apply.run_batch(urls, *, auto_submit)` and `apply.main(url, *, auto_submit)` route any ATS while preserving their return shapes (`list[dict]` and `dict`) and the no-URL "fill current Workday tab" behavior.

- [ ] **Step 1: Replace `apply.run_batch` body (keep the signature) with a delegator**

Replace the entire `run_batch` function (lines 430-480) with:

```python
def run_batch(urls: list[str], *, auto_submit: bool = True) -> list[dict]:
    """Apply to multiple jobs (any supported ATS). Delegates to the shared dispatcher."""
    from .ats import run_batch as ats_run_batch
    return [r.to_dict() for r in ats_run_batch(urls, auto_submit=auto_submit)]
```

(The `_save_report`/`REPORT_PATH` and the rich-table logic now live in `ats.run_batch`; the local `_save_report`/`REPORT_PATH` definitions in `apply.py` become unused — leave them, they harm nothing and are referenced by `_submit_and_record`/tests if any. If `_save_report` has no remaining references, remove it and `REPORT_PATH`.)

- [ ] **Step 2: Re-point `apply.main` to dispatch when a URL is given**

Replace the `main` function (lines 483-496) with:

```python
def main(url: str | None = None, *, auto_submit: bool = False) -> dict:
    """Single-job entry point. With a URL, route via the ATS dispatcher; without one,
    fill the current Workday tab (unchanged behavior)."""
    if url:
        from .ats import dispatch
        with sync_playwright() as pw:
            b = browser.connect(pw)
            page = browser.find_any_tab(b)
            if not page:
                console.print("[red]No Chrome tab available.[/red]")
                return {"status": "error", "reason": "No Chrome tab available"}
            result = dispatch(page, url, auto_submit=auto_submit).to_dict()
            b.close()
            return result
    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_workday_tab(b)
        if not page:
            console.print("[red]No Chrome tab available.[/red]")
            return {"status": "error", "reason": "No Chrome tab available"}
        result = _run_one(page, auto_submit=auto_submit)
        b.close()
        return result
```

- [ ] **Step 3: Verify imports + full suite (no import cycle, no regression)**

Run: `./venv/bin/python -c "import src.apply; from src.apply import run_batch, main; print('import ok')"`
Run: `./venv/bin/pytest -q`
Expected: `import ok`; all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/apply.py
git commit -m "feat(ats): route apply.py CLI through shared dispatch (#2)"
```

- [ ] **Step 5: Live verification (manual — needs Chrome on CDP)**

Launch Chrome (`scripts/launch_chrome.sh`), then:

```bash
# Lever via the unified single-job CLI — should fill + stop (review or captcha)
./venv/bin/python -c "from src.apply import main; print(main('https://jobs.lever.co/hive/fb175ecc-b6ba-4242-a84a-8699f9b0e971/apply', auto_submit=False))"
# Mixed batch through the shared runner — both routed correctly
./venv/bin/python -c "from src.ats import run_batch; [print(r.to_dict()['status'], r.job.get('tenant') or r.job.get('company')) for r in run_batch(['https://jobs.lever.co/hive/fb175ecc-b6ba-4242-a84a-8699f9b0e971/apply'], auto_submit=False)]"
```

Expected: the Lever call returns a `review`/`captcha` dict (filled, not submitted); the batch routes the Lever URL to the Lever driver (status printed, `report.yaml` written). Optionally add a real Workday URL to confirm no Workday regression.

---

## Self-Review

**Spec coverage:**
- `ApplyStatus`/`ApplyResult`/`ATSDriver` contract → Task 1. ✓
- `to_dict`/`from_dict` back-compat → Task 1 (tests round-trip + status strings). ✓
- `WorkdayDriver`/`LeverDriver` wrap unchanged runners → Task 2. ✓
- Driver owns navigation → Task 2 (WorkdayDriver `goto`; test asserts `goto_url`). ✓
- Registry + `driver_for` + `dispatch` (unknown→ERROR) + `run_batch` → Task 3. ✓
- Route agent single/batch + web runner → Task 4. ✓
- Re-point `apply.py` CLI → Task 5. ✓
- Workday internals untouched → constraint; Tasks only add wrappers/edits to CLI entry + consumers, never `_run_one`/`detect`/`FILLERS`. ✓
- Testing: offline units (Tasks 1-4) + live (Task 5). `run_batch` browser orchestration is verified live, consistent with the project's treatment of browser code. ✓

**Placeholder scan:** No TBD/TODO; every code step is complete. The one conditional ("if `_save_report` has no references, remove it") is an explicit either/or with both branches safe, not a placeholder. ✓

**Type consistency:** `ApplyStatus`/`ApplyResult`/`from_dict`/`to_dict`/`dispatch`/`driver_for`/`run_batch` names and signatures match across Tasks 1-5. `dispatch(page, url, *, auto_submit) -> ApplyResult` used identically by Task 4 consumers and Task 5 CLI. `.to_dict()` applied wherever a flat dict is expected. ✓
