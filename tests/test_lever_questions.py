import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats import lever
from src.questions import FLAG

PROFILE = {
    "education": [
        {"school": "Stony Brook", "gpa": "3.5", "end": "2027-06", "current": True},
        {"school": "St. Joseph's", "gpa": "3.93", "end": "2022-06", "current": False},
    ],
    "sensitive": {"requires_sponsorship": "No", "work_authorization": "Yes"},
    "preferences": {"how_did_you_hear": "Job Board > LinkedIn"},
}


def test_gpa_uses_current_education():
    assert lever.gpa(PROFILE) == "3.5"


def test_answer_custom_gpa():
    assert lever.answer_custom("What is/was your GPA?", PROFILE) == "3.5"


def test_answer_custom_sponsorship_from_profile():
    ans = lever.answer_custom(
        "Will you now or in the future require sponsorship for employment?", PROFILE)
    assert ans == "No"


def test_answer_custom_sensitive_unanswered_flags():
    ans = lever.answer_custom("Will you require sponsorship?", {"sensitive": {}})
    assert ans is FLAG


def test_answer_custom_unknown_returns_none():
    assert lever.answer_custom("What is your favorite color?", PROFILE) is None


def test_choose_checkbox_matches_how_did_you_hear():
    options = ["Friend", "Recruiter/current employee", "LinkedIn", "AngelList", "Other"]
    assert lever.choose_checkbox("How did you hear about us?", options, PROFILE) == "LinkedIn"


def test_choose_checkbox_no_match_returns_none():
    options = ["Friend", "Recruiter/current employee"]
    assert lever.choose_checkbox("How did you hear about us?", options, PROFILE) is None
