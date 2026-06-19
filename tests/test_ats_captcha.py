import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats.captcha import CAPTCHA_SEL, has_captcha


class FakeLocator:
    def __init__(self, n): self._n = n
    def count(self): return self._n


class FakePage:
    def __init__(self, n): self._n = n
    def locator(self, sel):
        assert sel == CAPTCHA_SEL
        return FakeLocator(self._n)


def test_captcha_sel_covers_recaptcha_hcaptcha_turnstile():
    for token in ["hcaptcha", "recaptcha", "turnstile", "g-recaptcha-response"]:
        assert token in CAPTCHA_SEL


def test_has_captcha_true_when_present():
    assert has_captcha(FakePage(1)) is True


def test_has_captcha_false_when_absent():
    assert has_captcha(FakePage(0)) is False
