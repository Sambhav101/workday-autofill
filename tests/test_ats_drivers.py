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
