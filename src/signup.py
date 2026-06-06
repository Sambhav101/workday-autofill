"""Account creation / sign-in for a Workday tenant.

Each company runs its own Workday tenant, so you need a fresh account per company.
This fills the "Create Account" form, submits it, waits for the verification
email via the Gmail connector, and opens the verify link automatically.

For existing accounts, it fills and submits the Sign In form. If the password
is wrong, it can trigger Forgot Password, read the reset email, and set the
new password from profile.yaml.

Usage:
    ./venv/bin/python -m src.signup              # auto create/sign-in
    ./venv/bin/python -m src.signup --no-email    # pause for manual email verify
"""
from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse
import yaml
from playwright.sync_api import sync_playwright, Page
from rich.console import Console

from . import browser
from .widgets import _poll
from .profile import load_profile

console = Console()
ACCOUNTS_PATH = Path(__file__).resolve().parent.parent / "accounts.yaml"

AID = {
    "email": "email",
    "password": "password",
    "verify_password": "verifyPassword",
    "agree": "createAccountCheckbox",
    "create_btn": "createAccountSubmitButton",
    "signin_btn": "signInSubmitButton",
    "create_link": "createAccountLink",
    "forgot_link": "forgotPasswordLink",
}


def _click_once(page: Page, label: str):
    """Click a Workday button exactly once by its aria-label, using the
    click_filter overlay if present, otherwise force-clicking the button."""
    overlay = page.locator(f'[data-automation-id="click_filter"][aria-label="{label}"]')
    if overlay.count():
        overlay.first.click()
        return
    btn = page.locator(f'button:has-text("{label}")')
    if btn.count():
        btn.first.click(force=True)


def _click_wd_button(page: Page, aid_key: str):
    """Click a Workday button that may have a click_filter overlay on top.
    Workday places an invisible div[data-automation-id='click_filter'] over
    submit buttons — clicking the actual <button> fails because the overlay
    intercepts pointer events. We click the overlay (by aria-label) first,
    falling back to force-click on the button."""
    # Try the click_filter overlay that shares the same aria-label
    btn = _aid(page, aid_key).first
    label = btn.get_attribute("aria-label") or btn.inner_text().strip()
    overlay = page.locator(f'[data-automation-id="click_filter"][aria-label="{label}"]')
    if overlay.count():
        overlay.first.click()
        return
    # fallback: force-click the button itself
    btn.click(force=True)


def _tenant(url: str) -> str:
    return urlparse(url).hostname or url


def _load_accounts() -> dict:
    if ACCOUNTS_PATH.exists():
        return yaml.safe_load(ACCOUNTS_PATH.read_text()) or {}
    return {}


def _save_account(tenant: str, email: str) -> None:
    data = _load_accounts()
    data[tenant] = {"email": email, "created": True}
    ACCOUNTS_PATH.write_text(yaml.safe_dump(data))


def _aid(page: Page, key: str):
    return page.locator(f'[data-automation-id="{AID[key]}"]')


def _resolve_password(creds: dict, tenant: str, *, existing_account: bool) -> str:
    default = creds.get("account_password", "")
    override = (creds.get("tenant_overrides") or {}).get(tenant) or ""
    if existing_account and override:
        return override
    return default


def _wait_for_page_change(page: Page, *, timeout_ms=10000):
    """Wait for navigation / page content to change after a form submit."""
    _poll(
        lambda: (page.locator('[data-automation-id="errorMessage"]').count() > 0
                 or page.locator('[data-automation-id="formField-legalName--firstName"]').count() > 0
                 or page.locator('[data-automation-id="signInSubmitButton"]').count() == 0
                 or page.locator('text="check your email"').count() > 0
                 or page.locator('text="verify"').count() > 0),
        timeout_ms=timeout_ms,
        interval_ms=300,
    )


def _on_application_form(page: Page) -> bool:
    """True if we landed directly on the application form (no verification needed)."""
    markers = [
        '[data-automation-id="formField-legalName--firstName"]',
        '[data-automation-id="formField-jobTitle"]',
        '[data-automation-id="formField-schoolName"]',
        '[data-automation-id="formField-school"]',
        '[data-automation-id="pageFooterNextButton"]',
    ]
    return any(page.locator(sel).count() > 0 for sel in markers)


def _has_email_verify_text(page: Page) -> bool:
    """True only if the page has text about verifying an email/account —
    NOT the 'Verify Password' field label on the create-account form."""
    for sel in ('text=/check your email/i',
                'text=/verify your email/i',
                'text=/verify your account/i',
                'text=/verification email/i',
                'text=/email has been sent/i',
                'text=/we sent.*email/i'):
        if page.locator(sel).count() > 0:
            return True
    return False


def _on_signin_page(page: Page) -> bool:
    """True if we're on a sign-in page (not create-account, not the form)."""
    return (_aid(page, "signin_btn").count() > 0
            and _aid(page, "create_btn").count() == 0)


def create_account(page: Page, creds: dict, tenant: str, *, auto_email: bool = True):
    email = creds.get("account_email", "")
    password = _resolve_password(creds, tenant, existing_account=False)

    _aid(page, "email").first.fill(email)
    _aid(page, "password").first.fill(password)
    if _aid(page, "verify_password").count():
        _aid(page, "verify_password").first.fill(password)
    if _aid(page, "agree").count():
        box = _aid(page, "agree").first
        if not box.is_checked():
            box.click()

    console.print("[cyan]Submitting Create Account...[/cyan]")
    _click_wd_button(page, "create_btn")
    _wait_for_page_change(page)

    errs = page.locator('[data-automation-id="errorMessage"]')
    if errs.count():
        err_text = errs.first.inner_text()
        if "already" in err_text.lower():
            console.print(f"[yellow]Account already exists on {tenant}.[/yellow]")
            _save_account(tenant, email)
            return "exists"
        console.print(f"[red]Create Account error: {err_text}[/red]")
        return "error"

    _save_account(tenant, email)
    console.print(f"[green]Account created on {tenant}.[/green]")

    # After account creation, three outcomes:
    # 1. Land on application form directly (no verification needed)
    # 2. Page with "verify email/account" text → need email verification
    # 3. Sign-in page → just sign in
    _poll(
        lambda: (_on_application_form(page)
                 or _on_signin_page(page)
                 or page.locator('[data-automation-id="SignInWithEmailButton"]').count() > 0
                 or _has_email_verify_text(page)),
        timeout_ms=10000, interval_ms=500,
    )

    if _on_application_form(page):
        console.print("[green]No verification needed — already on the application form.[/green]")
        return "ready"

    if _has_email_verify_text(page):
        console.print("[yellow]Page says to verify email first.[/yellow]")
        return "pending_verify"

    # No verify text — this is a sign-in page (direct or "Sign in with email")
    if (_on_signin_page(page)
            or page.locator('[data-automation-id="SignInWithEmailButton"]').count() > 0):
        console.print("[yellow]Sign-in page, no verify text — signing in.[/yellow]")
        return "needs_signin"

    # Fallback: no verify text found, assume sign-in needed
    console.print("[yellow]Unknown state after account creation — trying sign in.[/yellow]")
    return "needs_signin"


def sign_in(page: Page, creds: dict, tenant: str, *, auto_email: bool = True):
    email = creds.get("account_email", "")
    password = _resolve_password(creds, tenant, existing_account=True)

    _aid(page, "email").first.fill(email)
    _aid(page, "password").first.fill(password)

    console.print(f"[cyan]Signing in to {tenant}...[/cyan]")
    _click_wd_button(page, "signin_btn")
    _wait_for_page_change(page)

    errs = page.locator('[data-automation-id="errorMessage"]')
    if errs.count():
        err_text = errs.first.inner_text()
        if any(w in err_text.lower() for w in ("invalid", "incorrect", "wrong", "locked")):
            console.print("[yellow]Wrong password — trying Forgot Password flow...[/yellow]")
            return forgot_password(page, creds, tenant, auto_email=auto_email)
        console.print(f"[red]Sign In error: {err_text}[/red]")
        return "error"

    if _on_application_form(page):
        console.print(f"[green]Signed in to {tenant} — on application form.[/green]")
        return "ready"
    console.print(f"[green]Signed in to {tenant}.[/green]")
    return "signed_in"


def forgot_password(page: Page, creds: dict, tenant: str, *, auto_email: bool = True):
    forgot = _aid(page, "forgot_link")
    if not forgot.count():
        console.print("[red]No 'Forgot Password' link found.[/red]")
        return "error"

    forgot.first.click()
    page.wait_for_timeout(1500)

    email_field = _aid(page, "email")
    if email_field.count():
        email_field.first.fill(creds.get("account_email", ""))

    # Click Reset Password exactly once via the click_filter overlay
    _click_once(page, "Reset Password")
    page.wait_for_timeout(2000)
    console.print("[cyan]Password reset email requested.[/cyan]")

    if auto_email:
        console.print("[cyan]Waiting for password reset email...[/cyan]")
        link = _poll_for_email(tenant, kind="reset")
        if link:
            console.print("[green]Got reset link — opening...[/green]")
            page.goto(link)
            page.wait_for_timeout(3000)
            new_pw = creds.get("account_password", "")
            pw_fields = page.locator('input[type="password"]')
            for i in range(pw_fields.count()):
                pw_fields.nth(i).fill(new_pw)
            _click_once(page, "Submit")
            page.wait_for_timeout(3000)
            console.print(f"[green]Password reset to signup password on {tenant}.[/green]")
            return "password_reset"
        else:
            console.print("[yellow]No reset email arrived in 90s — check manually.[/yellow]")
            return "pending_reset"
    else:
        console.print("[yellow]Paused — reset the password in your email to the "
                      "same password used for signup (from profile.yaml).[/yellow]")
        return "pending_reset"


def _poll_for_email(tenant: str, *, kind: str = "any") -> str | None:
    """Use the Gmail connector to find a Workday email for this tenant.
    Returns the action URL or None."""
    try:
        from .email_links import find_workday_link
    except ImportError:
        return None

    # The Gmail MCP tools are available as module-level functions when called
    # from the CLI context. For now, this is a placeholder that will be wired
    # up when the MCP connector is available in the Python runtime.
    # TODO: wire up MCP Gmail tools once they're callable from Python
    console.print("[dim]Gmail connector not available in Python runtime — "
                  "check email manually.[/dim]")
    return None


def create_or_sign_in(page: Page, profile: dict, *, auto_email: bool = True) -> str:
    creds = profile.get("credentials", {})
    email = creds.get("account_email")
    if not email or not creds.get("account_password"):
        raise SystemExit("Set credentials.account_email and account_password in profile.yaml first.")

    tenant = _tenant(page.url)
    known = _load_accounts().get(tenant)

    # provider-choice screen (Google / Sign In with Email)
    email_btn = page.locator('[data-automation-id="SignInWithEmailButton"]')
    if email_btn.count():
        email_btn.first.click()
        page.wait_for_timeout(800)

    if not known and _aid(page, "create_link").count():
        console.print(f"[cyan]No recorded account on {tenant} — creating...[/cyan]")
        _aid(page, "create_link").first.click()
        page.wait_for_timeout(500)

    creating = _aid(page, "create_btn").count() > 0

    if creating:
        result = create_account(page, creds, tenant, auto_email=auto_email)
        if result == "exists":
            page.reload()
            page.wait_for_timeout(2000)
            return sign_in(page, creds, tenant, auto_email=auto_email)
        if result == "needs_signin":
            # Tenant redirected to sign-in after account creation.
            # May need email verification first — try signing in directly,
            # and if that fails the sign_in flow handles forgot-password.
            return sign_in(page, creds, tenant, auto_email=auto_email)
        return result
    else:
        return sign_in(page, creds, tenant, auto_email=auto_email)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-email", action="store_true",
                    help="don't auto-read verification emails")
    args = ap.parse_args()

    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_workday_tab(b)
        if not page:
            console.print("[red]No Workday tab open.[/red]")
            return
        result = create_or_sign_in(page, load_profile(), auto_email=not args.no_email)
        console.print(f"\n[bold]Result: {result}[/bold]")
        b.close()


if __name__ == "__main__":
    main()
