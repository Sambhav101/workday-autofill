import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats import lever


def test_lever_job_meta_basic():
    m = lever.lever_job_meta("https://jobs.lever.co/hive/fb175ecc-b6ba-4242-a84a-8699f9b0e971/apply")
    assert m["company"] == "hive"
    assert m["tenant"] == "hive"
    assert m["job_id"] == "fb175ecc-b6ba-4242-a84a-8699f9b0e971"


def test_lever_job_meta_without_apply_suffix():
    m = lever.lever_job_meta("https://jobs.lever.co/quizlet-2/4e5e411e-2bb7")
    assert m["company"] == "quizlet-2"
    assert m["job_id"] == "4e5e411e-2bb7"


def test_lever_job_meta_handles_sparse_path():
    m = lever.lever_job_meta("https://jobs.lever.co/onlycompany")
    assert m["company"] == "onlycompany"
    assert m["tenant"] == "onlycompany"
    assert m["job_id"] == ""
