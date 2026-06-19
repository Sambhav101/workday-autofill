# ATSDriver Interface + Unified Dispatch — Design Doc

**Date:** 2026-06-19
**Issue:** #2 (follow-up to the merged Lever spike, PR #7)
**Status:** Approved — ready for implementation plan

## Context

After the Lever spike (merged), the project has **two** real ATS implementations of
very different shapes:

- **Workday** (`src/apply.py`) — a multi-page wizard with a mandatory apply-button /
  sign-in pre-flow. Entry: `_run_one(page, *, auto_submit, max_pages)`; caller
  navigates first.
- **Lever** (`src/ats/lever.py`) — a single-page form, no account. Entry:
  `apply_one(url, *, auto_submit, page)`; self-navigates (appends `/apply`).

Both already return the same loose shape: `{status, reason, **job_metadata}`, with
nearly the same status vocabulary. This is the right moment to extract a shared
interface — the abstraction now comes from two concrete, differing cases rather
than being guessed from Workday alone (the reason Lever was built as a spike first).

### The bug this also fixes

Routing exists in only one of three consumers:

- `agent/tools.py:_apply_to_job` — routes Lever vs Workday correctly.
- `agent/tools.py:_apply_batch` — calls `apply.run_batch` (**Workday-only**).
- `web/runner.py:run_queue` worker — calls `apply._run_one` directly (**Workday-only**).

So a Lever URL queued through the web UI or run as a batch is silently fed to the
Workday driver and mishandled. A single dispatcher used by all three consumers fixes
this today, not just in the future.

## Goals

- A uniform `ATSDriver` contract every ATS implements and every consumer dispatches
  against.
- A typed result (`ApplyResult` + `ApplyStatus`) replacing the loose status strings,
  with a back-compat `to_dict()` for consumers that still read flat keys.
- All three consumers route through one dispatcher (fixing the web/batch Lever bug).
- The mature Workday path's internals are not modified — it is wrapped, not rewritten.

## Non-goals / out of scope

- Consolidating shared helpers (captcha detection, required-field brake, dedup/record)
  into the shared layer. Deferred until a third ATS (Greenhouse/Ashby) shows what is
  genuinely common. Captcha-status surfacing in the UI is tracked separately (#8).
- Greenhouse and Ashby drivers (separate specs).
- Changing either driver's page-handling behavior.

## Architecture

### Component 1 — the contract (`src/ats/base.py`, new)

```python
class ApplyStatus(str, Enum):
    SUBMITTED = "submitted"
    REVIEW    = "review"
    BLOCKED   = "blocked"
    CAPTCHA   = "captcha"
    SKIPPED   = "skipped"
    ERROR     = "error"

@dataclass(frozen=True)
class ApplyResult:
    status: ApplyStatus
    reason: str
    job: dict                       # title/tenant/url/job_id/company/...
    def to_dict(self) -> dict:
        return {"status": self.status.value, "reason": self.reason, **self.job}

class ATSDriver(Protocol):
    name: str
    def apply(self, page, url: str, *, auto_submit: bool) -> ApplyResult: ...
```

Subclassing `str` for `ApplyStatus` keeps `to_dict()` output identical to today's
string statuses, so consumers and `applications.yaml`/`report.yaml` are unaffected.

**Seam decision — the driver owns navigation.** The dispatcher hands a driver a
`page` and the `url`; the driver performs its own `goto` and any pre-flow. Rationale:
navigation specifics are ATS-specific (Lever's `/apply` suffix, Workday's apply-button
→ sign-in → wizard). A "dispatcher pre-navigates" model would leak those specifics
into the shared layer. Cost: the two consumers that currently pre-navigate
(`tools`, `web/runner`) stop doing so and let the driver navigate.

### Component 2 — drivers wrap existing code

- `src/ats/workday.py` (new) — `WorkdayDriver`:
  ```python
  name = "workday"
  def apply(self, page, url, *, auto_submit):
      page.goto(url); page.wait_for_timeout(5000)
      return ApplyResult.from_dict(apply_run_one(page, auto_submit=auto_submit))
  ```
  `apply._run_one` is unchanged. Its pre-flow (apply button, signup) already runs
  inside `_run_one`.
- `src/ats/lever.py` (modify) — add `LeverDriver`:
  ```python
  name = "lever"
  def apply(self, page, url, *, auto_submit):
      return ApplyResult.from_dict(apply_one(url, auto_submit=auto_submit, page=page))
  ```
  Existing pure/browser functions are untouched.

A small `ApplyResult.from_dict(d)` classmethod maps a legacy
`{status, reason, **job}` dict into the dataclass (pops `status`/`reason`, the rest is
`job`; coerces the status string to `ApplyStatus`). This keeps the wrappers one line
and avoids editing the drivers' internal return statements.

### Component 3 — dispatcher + registry (`src/ats/__init__.py`, modify)

```python
_REGISTRY: dict[str, ATSDriver] = {"workday": WorkdayDriver(), "lever": LeverDriver()}

def driver_for(url: str) -> ATSDriver | None:
    return _REGISTRY.get(detect_ats(url))           # detect_ats already exists

def dispatch(page, url, *, auto_submit: bool) -> ApplyResult:
    d = driver_for(url)
    if d is None:
        return ApplyResult(ApplyStatus.ERROR, f"No driver for URL: {url}", {"url": url})
    return d.apply(page, url, auto_submit=auto_submit)

def run_batch(urls, *, auto_submit: bool = True) -> list[ApplyResult]:
    # one shared CDP browser; dispatch per URL; collect + report (rich table + report.yaml)
```

`run_batch` is the driver-agnostic batch loop — it opens one browser, calls `dispatch`
per URL, aggregates `ApplyResult`s, and writes the summary table + `report.yaml`
(logic relocated from `apply.run_batch`, which is already ATS-generic in its reporting).

### Component 4 — route the consumers

- `agent/tools.py:_apply_to_job(url)` → `dispatch(page, url, auto_submit=True).to_dict()`
  (replaces the inline Lever/Workday branch; uses the agent's persistent `_get_page()`).
- `agent/tools.py:_apply_batch(urls)` → shared `run_batch(urls, auto_submit=True)`,
  returning `[r.to_dict() for r in ...]`.
- `web/runner.py` worker → `dispatch(page, url, auto_submit=auto_submit).to_dict()` per
  dequeued job (replaces the hardcoded `_run_one`; the worker no longer pre-navigates).
- `apply.py` — keeps all Workday internals. Its module-level `run_batch`/`main` are
  re-pointed at the shared `ats.run_batch`/`ats.dispatch` so `python -m src.apply`
  gains correct Lever handling. (The Workday-specific helpers `detect`, `FILLERS`,
  `_check_required_fields`, `_run_one` remain for the agent's page-level tools.)

## Data flow

```
URL ──> dispatch(page, url, auto_submit)
          └─ driver_for(url)  [detect_ats]
               ├─ "workday" ─> WorkdayDriver.apply ─> goto + _run_one ─┐
               ├─ "lever"   ─> LeverDriver.apply   ─> apply_one ───────┤
               └─ None      ─> ApplyResult(ERROR) ──────────────────────┤
                                                                        ▼
                                                            ApplyResult{status,reason,job}
                                                                        │
                              consumers call .to_dict() where flat dict is expected
                              (web events, report.yaml, applications.yaml, agent tools)
```

## Failure modes / risks

- **Regression in the mature Workday path** → mitigated: `_run_one` and all Workday
  helpers are untouched; `WorkdayDriver` only adds the `goto`+wrap the consumers
  already did. Covered by a live Workday run before merge.
- **Status string drift** → `ApplyStatus(str, Enum)` guarantees `to_dict()` emits the
  same strings used today; a unit test asserts the exact vocabulary.
- **Consumer reads a job field the dataclass dropped** → `from_dict` keeps every
  non-`status`/`reason` key in `job`, and `to_dict` re-spreads them, so the flat shape
  is byte-equivalent. A unit test round-trips a representative dict.
- **Navigation ownership shift** breaks a consumer that still pre-navigates → all three
  consumers are updated in the same change; a double-`goto` would be harmless but is
  removed.

## Testing

- **Unit (offline, drivers stubbed):**
  - `detect_ats` → `driver_for` returns the right driver instance; unknown host → None.
  - `ApplyResult.to_dict()` / `from_dict()` round-trip preserves all keys and emits the
    legacy status strings.
  - `dispatch` returns an `ERROR` `ApplyResult` for an unknown host without raising.
  - `run_batch` aggregates a mixed list of stubbed results in order.
- **Live (manual, before merge):** one Workday URL and one Lever URL through `dispatch`
  (and a 2-URL mixed `run_batch`) to confirm no regression and correct routing.

## Rollout

1. Add `base.py` (contract + result type) with unit tests.
2. Add `workday.py` driver + `LeverDriver`; wire the registry and `dispatch`/`run_batch`.
3. Route the three consumers; re-point `apply.py` CLI.
4. Live-verify one Workday + one Lever job.
5. Merge. Greenhouse/Ashby and shared-helper consolidation follow as separate specs.

## Open questions

None — scope (thin interface + unified dispatch), result type (dataclass + status
enum), navigation ownership (driver-owned), and the `apply.py` CLI (routed through
shared dispatch) are all resolved.
