"""Shared captcha detection across ATS drivers. A present challenge means the
form cannot be auto-submitted — the human solves it and submits."""
from __future__ import annotations

CAPTCHA_SEL = ('#h-captcha, .h-captcha, iframe[src*="hcaptcha"], '
               '.g-recaptcha, iframe[src*="recaptcha"], '
               'iframe[src*="turnstile"], textarea[name="g-recaptcha-response"]')


def has_captcha(page) -> bool:
    """True if the page shows an hCaptcha/reCAPTCHA/Turnstile challenge."""
    return page.locator(CAPTCHA_SEL).count() > 0
