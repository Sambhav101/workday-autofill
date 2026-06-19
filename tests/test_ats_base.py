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
