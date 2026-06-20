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
