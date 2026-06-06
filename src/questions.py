"""Fill the Workday "Application Questions" screening page. These fields have
random per-tenant GUID ids, so we map by the QUESTION TEXT via keyword rules.
Unrecognized questions fall through to the LLM resolver (resolver.py); anything
the resolver returns UNSURE on is flagged for manual entry. Stops before submit.

    ./venv/bin/python -m src.questions
"""
from __future__ import annotations

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

RULES = [
    (["sponsorship"], "No"),
    (["legal age"], "Yes"),
    (["background check"], "Yes"),
    (["identity", "right to work"], "Yes"),
    (["right to work"], "Yes"),
    (["able to work", "relocate"], "Yes"),
    (["relocate"], "Yes"),
    (["authorized to work"], "Yes"),
    (["non-compete"], "No"),
    (["non-disclosure"], "No"),
    (["restrictive covenant"], "No"),
    (["post-employment"], "No"),
    (["post employment"], "No"),
    (["involuntarily discharged"], "No"),
    (["asked to resign"], "No"),
    (["worked for"], "No"),
    (["worked at"], "No"),
    (["related to anyone"], "No"),
    (["close personal relationship"], "No"),
    (["familial relationship"], "No"),
    (["familial relationships"], "No"),
    (["government office"], "No"),
    (["government agency"], "No"),
    (["outside employment"], "No"),
    (["engage with", "contracts"], "No"),
    (["conflict of interest"], "No"),
    (["arbitration"], "Yes"),
    (["current associate"], "No"),
    (["current employee"], "No"),
    (["eligible for employment"], "Yes"),
    (["legally eligible"], "Yes"),
    (["18 years"], "Yes"),
    (["age or older"], "Yes"),
    (["able to perform"], "Yes"),
    (["previously worked for"], "No"),
    (["us citizen"], "No"),
    (["permanent resident"], "No"),
    (["refugee"], "No"),
    (["asylum"], "No"),
    (["citizen", "permanent resident"], "No"),
    (["interviewed before"], "No"),
    (["interviewed with"], "No"),
    (["previously interviewed"], "No"),
    (["taken exam"], "No"),
    (["taken any exam"], "No"),
    (["hold any certification"], "No"),
    (["certifications do you hold"], "No"),
    (["clubs or org"], "No"),
    (["organizations do you"], "No"),
    (["member of any"], "No"),
    (["immediate family"], "No"),
    (["debarred"], "No"),
    (["suspended", "ineligible"], "No"),
    (["communication", "preference"], "No"),
    (["future position"], "No"),
    (["future opening"], "No"),
    (["receive communication"], "No"),
    (["preferred", "location"], "New York|No preference|No Preference"),
    (["geographic", "location"], "New York|No preference|No Preference"),
    (["preferred", "geographic"], "New York|No preference|No Preference"),
    (["location preference"], "New York|No preference|No Preference"),
]


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
        ans = _answer_for(q)
        short = q[:55]

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
    # Some tenants have free-text inputs (discharge explanation, desired salary).
    # Discover them and fill with known defaults.
    profile = load_profile()
    prefs = profile.get("preferences", {})
    identity = profile.get("identity", {})
    full_name = f"{identity.get('first_name', '')} {identity.get('last_name', '')}".strip()
    TEXT_RULES = [
        (["graduation", "date"], "June 2027"),
        (["anticipated graduation"], "June 2027"),
        (["expected graduation"], "June 2027"),
        (["major"], profile.get("education", [{}])[0].get("field", "Computer Science")),
        (["current gpa"], str(profile.get("education", [{}])[0].get("gpa", "3.5"))),
        (["overall gpa"], str(profile.get("education", [{}])[0].get("gpa", "3.5"))),
        (["cumulative gpa"], str(profile.get("education", [{}])[0].get("gpa", "3.5"))),
        (["certification"], "None"),
        (["clubs"], "None"),
        (["organizations"], "None"),
        (["discharged", "suspended", "terminated", "resign"], "N/A"),
        (["desired", "compensation"], prefs.get("desired_salary", "120000")),
        (["desired", "salary"], prefs.get("desired_salary", "120000")),
        (["expect to earn"], prefs.get("desired_salary", "120000")),
        (["expected salary"], prefs.get("desired_salary", "120000")),
        (["salary expectation"], prefs.get("desired_salary", "120000")),
        (["compensation expectation"], prefs.get("desired_salary", "120000")),
        (["earliest", "start"], prefs.get("earliest_start_date", "ASAP")),
        (["desired", "start date"], prefs.get("earliest_start_date", "ASAP")),
        (["start date"], prefs.get("earliest_start_date", "ASAP")),
        (["certify", "typing my name"], full_name),
        (["certify", "true and accurate"], full_name),
        (["electronic signature"], full_name),
        (["preferred", "location"], "New York"),
        (["geographic", "location"], "New York"),
        (["location preference"], "New York"),
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
                ok, note = widgets.fill_text(page, f["aid"], str(ans))
                results.append((q_low[:55], str(ans), ok, note))
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
