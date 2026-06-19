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


def test_dispatch_routes_to_workday(monkeypatch):
    import src.apply as apply_mod
    monkeypatch.setattr(apply_mod, "_run_one",
                        lambda page, *, auto_submit:
                        {"status": "review", "reason": "ok", "tenant": "acme"})
    r = dispatch(FakePage(), "https://acme.wd5.myworkdayjobs.com/job/x", auto_submit=False)
    assert r.status is ApplyStatus.REVIEW
    assert r.job["tenant"] == "acme"


def test_driver_for_maps_ashby():
    from src.ats.ashby import AshbyDriver
    assert isinstance(driver_for("https://jobs.ashbyhq.com/voleon/abc/application"), AshbyDriver)


def test_dispatch_routes_to_ashby(monkeypatch):
    import src.ats.ashby as ashby_mod
    monkeypatch.setattr(ashby_mod, "apply_one",
                        lambda url=None, *, auto_submit=False, page=None:
                        {"status": "captcha", "reason": "solve it", "company": "voleon"})
    r = dispatch(FakePage(), "https://jobs.ashbyhq.com/voleon/abc/application", auto_submit=True)
    assert r.status is ApplyStatus.CAPTCHA
    assert r.job["company"] == "voleon"
