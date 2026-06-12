"""Fill the Workday "Application Questions" screening page. These fields have
random per-tenant GUID ids, so we map by the QUESTION TEXT via keyword rules.
Unrecognized questions fall through to the LLM resolver (resolver.py); anything
the resolver returns UNSURE on is flagged for manual entry. Stops before submit.

    ./venv/bin/python -m src.questions
"""
from __future__ import annotations

from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright, Page
from rich.console import Console
from rich.table import Table

from . import browser, widgets
from .widgets import close_popups, _wait_for_options, _click_option, OPTION_SEL
from .discover import discover_fields
from .profile import load_profile
from .resolver import resolve_choice, available as resolver_available

console = Console()

_RESOLVER_THRESHOLD = 0.6

# Keyword rules for common screening questions live in an editable YAML file
# (screening_rules.yaml) so users can change answers without touching Python.
# Sensitive questions (visa/work-auth/citizenship/salary) are NOT here — they come
# from the user's profile via `_sensitive_answer` and the text rules, or are flagged.
RULES_PATH = Path(__file__).resolve().parent.parent / "screening_rules.yaml"


def load_rules(path: Path = RULES_PATH) -> list[tuple[list[str], str]]:
    """Load screening rules as (keywords, answer) tuples. Missing file -> no rules
    (questions then rely on the profile + LLM resolver, or get flagged)."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    rules: list[tuple[list[str], str]] = []
    for r in data.get("rules", []):
        match = r.get("match", [])
        if isinstance(match, str):
            match = [match]
        kws = [str(k).strip().lower() for k in match if str(k).strip()]
        ans = str(r.get("answer", "")).strip()
        if kws and ans:
            rules.append((kws, ans))
    return rules


RULES = load_rules()


def _question_for(page: Page, el_handle) -> str:
    return el_handle.evaluate(r"""el => {
        let p = el;
        for (let d = 0; d < 8 && p; d++) {
            const l = p.querySelector('label, legend');
            if (l && l.innerText.trim()) return l.innerText.trim();
            p = p.parentElement;
        }
        return '';
    }""")


def _question_for_aid(page: Page, aid: str) -> str:
    """Get the question label for a field by its automation ID."""
    el = page.locator(f'[data-automation-id="{aid}"]')
    if not el.count():
        return ""
    return _question_for(page, el.first)


def _answer_for(question: str) -> str | None:
    q = question.lower()
    for kws, ans in RULES:
        if all(k in q for k in kws):
            return ans
    return None


# Sentinel: the question IS a sensitive one (visa/citizenship/work-auth) but the
# profile doesn't clearly answer it, so it must be flagged for the human — never guessed.
FLAG = object()


def _yes_no(value: str) -> str | None:
    v = str(value).strip().lower()
    if v in ("yes", "y", "true", "1"):
        return "Yes"
    if v in ("no", "n", "false", "0"):
        return "No"
    return None


def _work_auth_answer(work_authorization: str) -> str | None:
    """Map a free-text work_authorization to Yes/No for 'are you authorized to work'."""
    t = str(work_authorization).strip().lower()
    if not t:
        return None
    if any(n in t for n in ("not authorized", "not eligible", "no authorization", "unauthorized")):
        return "No"
    if any(p in t for p in ("authorized", "eligible", "citizen", "permanent resident",
                            "green card", "yes")):
        return "Yes"
    return None


def _sensitive_answer(question: str, profile: dict):
    """Answer visa/work-auth/citizenship questions from the profile.

    Returns a "Yes"/"No" string when the profile clearly answers it, FLAG when the
    question is sensitive but the profile is silent (-> manual entry), or None when
    the question isn't in this sensitive category (-> normal rules/LLM).
    """
    q = question.lower()
    sens = profile.get("sensitive", {})
    work_auth = sens.get("work_authorization", "")

    # Visa sponsorship — driven purely by profile.requires_sponsorship
    if "sponsorship" in q or ("sponsor" in q and "visa" in q):
        ans = _yes_no(sens.get("requires_sponsorship", ""))
        return ans if ans is not None else FLAG

    # Work authorization / legally eligible / right to work
    if any(k in q for k in ("authorized to work", "legally authorized", "legally eligible",
                            "right to work", "eligible for employment")):
        ans = _work_auth_answer(work_auth)
        return ans if ans is not None else FLAG

    # Citizenship / permanent residency — answer ONLY if the profile literally
    # states it; do not infer citizenship from mere work authorization.
    if "citizen" in q:
        return "Yes" if "citizen" in str(work_auth).lower() else FLAG
    if "permanent resident" in q or "green card" in q:
        wa = str(work_auth).lower()
        return "Yes" if ("permanent resident" in wa or "green card" in wa) else FLAG
    if "refugee" in q or "asylum" in q:
        return FLAG

    return None


_MONTHS = ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]


def _grad_date(profile: dict) -> str:
    """Graduation date as 'Month YYYY', from the current (or latest-ending) degree.
    Returns '' if no education end date is set, so it gets flagged for manual entry."""
    eds = profile.get("education") or []
    chosen = next((e for e in eds if e.get("current")), None)
    if chosen is None:
        with_end = [e for e in eds if str(e.get("end", "")).strip()]
        chosen = max(with_end, key=lambda e: str(e["end"]), default=None)
    if not chosen:
        return ""
    end = str(chosen.get("end", "")).strip()
    parts = end.split("-")
    if len(parts) >= 2 and parts[1].isdigit() and 1 <= int(parts[1]) <= 12:
        return f"{_MONTHS[int(parts[1])]} {parts[0]}"
    return end


def _read_open_options(page: Page) -> list[str]:
    items = page.locator(OPTION_SEL)
    opts = []
    for i in range(items.count()):
        try:
            it = items.nth(i)
            if it.is_visible():
                txt = (it.inner_text() or "").strip()
                if txt:
                    opts.append(txt)
        except Exception:  # noqa: BLE001
            pass
    return opts


def _open_dropdown(page: Page, btn, *, retries: int = 2) -> bool:
    for attempt in range(retries + 1):
        close_popups(page)
        try:
            btn.scroll_into_view_if_needed()
            btn.click()
        except Exception:  # noqa: BLE001
            continue
        if _wait_for_options(page):
            return True
    return False


def fill_questions(page: Page, job_title: str = ""):
    results = []
    profile = load_profile()
    btns = page.locator('button[aria-haspopup="listbox"]')
    for i in range(btns.count()):
        btn = btns.nth(i)
        try:
            if not btn.is_visible():
                continue
        except Exception:
            continue
        q = _question_for(page, btn)
        if not q:
            continue
        short = q[:55]

        # Sensitive questions (visa/work-auth/citizenship) come straight from the
        # profile, or are flagged for manual entry — never from hardcoded answers.
        sens = _sensitive_answer(q, profile)
        if sens is FLAG:
            results.append((short, "—", False,
                            "SENSITIVE — answer manually (set it in profile.yaml or in Chrome)"))
            continue
        ans = sens if isinstance(sens, str) else _answer_for(q)

        if ans is None:
            # LLM resolver path: open dropdown, read options, ask Claude
            if not _open_dropdown(page, btn):
                results.append((short, "—", False, "couldn't open dropdown"))
                continue
            options = _read_open_options(page)
            close_popups(page)

            if options and resolver_available():
                resolved = resolve_choice(q, options, job_title=job_title)
                r_ans = resolved.get("answer", "UNSURE")
                r_conf = resolved.get("confidence", 0.0)
                r_reason = resolved.get("reason", "")
                if r_ans == "UNSURE" or r_conf < _RESOLVER_THRESHOLD:
                    results.append((short, "—", False,
                                    f"LLM UNSURE ({r_conf:.0%}) — answer manually. {r_reason}"))
                    continue
                if not _open_dropdown(page, btn):
                    results.append((short, r_ans, False, "couldn't reopen dropdown"))
                    continue
                ok = _click_option(page, r_ans)
                note = f"LLM ({r_conf:.0%}): {r_reason[:60]}"
                results.append((short, r_ans, ok,
                                ("selected — " if ok else "option not found — ") + note))
            else:
                reason = "no API key" if not resolver_available() else "no options read"
                results.append((short, "—", False, f"UNRECOGNIZED — answer manually ({reason})"))
            continue

        # Rule-based answer — ans can be "val1|val2|val3" for fallbacks
        if not _open_dropdown(page, btn):
            results.append((short, ans, False, "couldn't open dropdown"))
            continue
        alternatives = [a.strip() for a in ans.split("|")]
        ok = False
        picked = alternatives[0]
        for alt in alternatives:
            ok = _click_option(page, alt)
            if ok:
                picked = alt
                break
        results.append((short, picked, ok, "selected" if ok else "option not found"))

    # ── text fields on the questions page ──────────────────────────────────
    # Free-text inputs (graduation date, GPA, desired salary, signature). Values
    # come from the profile; a rule whose value resolves to "" is FLAGGED for
    # manual entry rather than filled with an assumed default.
    prefs = profile.get("preferences", {})
    identity = profile.get("identity", {})
    edu0 = (profile.get("education") or [{}])[0]
    full_name = f"{identity.get('first_name', '')} {identity.get('last_name', '')}".strip()
    grad = _grad_date(profile)
    salary = str(prefs.get("desired_salary", "")).strip()
    start_date = str(prefs.get("earliest_start_date", "")).strip()
    TEXT_RULES = [
        (["graduation", "date"], grad),
        (["anticipated graduation"], grad),
        (["expected graduation"], grad),
        (["major"], str(edu0.get("field", ""))),
        (["current gpa"], str(edu0.get("gpa", ""))),
        (["overall gpa"], str(edu0.get("gpa", ""))),
        (["cumulative gpa"], str(edu0.get("gpa", ""))),
        (["certification"], "None"),
        (["clubs"], "None"),
        (["organizations"], "None"),
        (["discharged", "suspended", "terminated", "resign"], "N/A"),
        (["desired", "compensation"], salary),
        (["desired", "salary"], salary),
        (["expect to earn"], salary),
        (["expected salary"], salary),
        (["salary expectation"], salary),
        (["compensation expectation"], salary),
        (["earliest", "start"], start_date),
        (["desired", "start date"], start_date),
        (["start date"], start_date),
        (["certify", "typing my name"], full_name),
        (["certify", "true and accurate"], full_name),
        (["electronic signature"], full_name),
    ]
    fields = discover_fields(page)
    for f in fields:
        if f["widget"] != "text" or not f["visible"]:
            continue
        if f["value"]:
            continue
        label = f["label"].lower()
        q_text = _question_for_aid(page, f["aid"])
        q_low = (q_text or label).lower()
        for kws, ans in TEXT_RULES:
            if all(k in q_low for k in kws):
                val = str(ans).strip()
                if not val:
                    results.append((q_low[:55], "—", False,
                                    "needs a value — set it in profile.yaml or answer manually"))
                    break
                ok, note = widgets.fill_text(page, f["aid"], val)
                results.append((q_low[:55], val, ok, note))
                break

    # checkbox: "Have you ever worked at [company]" -> "I have not worked..."
    lbl = page.locator('label', has_text="I have not worked")
    if lbl.count():
        try:
            fid = lbl.first.get_attribute("for")
            box = page.locator(f'[id="{fid}"]') if fid else page.locator("x:nope")
            if box.count():
                box.first.scroll_into_view_if_needed()
                if not box.first.is_checked():
                    box.first.check()
            else:
                lbl.first.click()
            results.append(("Worked here before?", "Never", True, "checked 'have not'"))
        except Exception as e:  # noqa: BLE001
            try:
                lbl.first.click()
                results.append(("Worked here before?", "Never", True, "checked via label"))
            except Exception as e2:  # noqa: BLE001
                results.append(("Worked here before?", "Never", False, f"error: {e2}"))

    t = Table(title="Application Questions — review (nothing submitted)")
    t.add_column("Question"); t.add_column("Answer"); t.add_column("Result")
    for q, a, ok, note in results:
        if ok:
            mark = "[green]ok[/green]"
        elif "UNSURE" in note or "manually" in note:
            mark = "[yellow]FLAG[/yellow]"
        else:
            mark = "[red]NEEDS FIX[/red]"
        t.add_row(q, a, f"{mark} [dim]{note}[/dim]")
    console.print(t)
    flagged = sum(1 for _, _, ok, note in results if not ok)
    if flagged:
        console.print(f"\n[yellow]{flagged} question(s) need manual attention.[/yellow]")
    console.print("\n[bold]Stopped before submit.[/bold] Review in Chrome.")


def main():
    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_workday_tab(b)
        if not page:
            console.print("[red]No Workday tab open.[/red]")
            return
        fill_questions(page)
        b.close()


if __name__ == "__main__":
    main()
