import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats import detect_ats


def test_detects_lever():
    assert detect_ats("https://jobs.lever.co/hive/abc-123/apply") == "lever"


def test_detects_workday():
    assert detect_ats("https://adobe.wd5.myworkdayjobs.com/en-US/job/x") == "workday"


def test_unknown_host():
    assert detect_ats("https://boards.greenhouse.io/foo/jobs/1") == "unknown"


def test_garbage_url():
    assert detect_ats("not a url") == "unknown"


def test_lever_and_workday_distinct():
    assert detect_ats("https://jobs.lever.co/x/y/apply") != detect_ats(
        "https://x.myworkdayjobs.com/job")
