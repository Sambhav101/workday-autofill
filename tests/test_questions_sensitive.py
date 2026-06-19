"""Sensitive screening questions must come from the profile or be flagged —
never answered with a hardcoded default that imposes one person's situation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.questions import (
    _sensitive_answer, _grad_date, _work_auth_answer, _yes_no, _answer_for,
    load_rules, RULES, FLAG,
)


def test_screening_rules_yaml_loads():
    rules = load_rules()
    assert rules, "screening_rules.yaml should ship with rules"
    assert rules == RULES
    # every rule is (list-of-lowercase-keywords, non-empty answer)
    for kws, ans in rules:
        assert isinstance(kws, list) and kws and all(k == k.lower() for k in kws)
        assert isinstance(ans, str) and ans


def test_rules_answer_common_questions():
    assert _answer_for("Are you at least 18 years of age?") == "Yes"
    assert _answer_for("Do you have a non-compete agreement?") == "No"
    assert _answer_for("Do you agree to arbitration?") == "Yes"


def test_missing_rules_file_is_safe(tmp_path):
    assert load_rules(tmp_path / "nope.yaml") == []


def _profile(**sensitive):
    return {"sensitive": sensitive}


def test_sponsorship_from_profile():
    assert _sensitive_answer("Do you require visa sponsorship?", _profile(requires_sponsorship="Yes")) == "Yes"
    assert _sensitive_answer("Will you now or in future need sponsorship?", _profile(requires_sponsorship="No")) == "No"


def test_sponsorship_blank_is_flagged():
    assert _sensitive_answer("Do you require sponsorship?", _profile(requires_sponsorship="")) is FLAG


def test_work_authorization_from_profile():
    p = _profile(work_authorization="Authorized to work in the US")
    assert _sensitive_answer("Are you legally authorized to work in the United States?", p) == "Yes"


def test_work_authorization_blank_is_flagged():
    assert _sensitive_answer("Are you authorized to work here?", _profile(work_authorization="")) is FLAG


def test_citizenship_not_inferred_from_work_auth():
    # Authorized to work != citizen. Must flag, not answer "Yes".
    p = _profile(work_authorization="Authorized to work in the US")
    assert _sensitive_answer("Are you a US citizen?", p) is FLAG


def test_citizenship_answered_when_profile_states_it():
    p = _profile(work_authorization="US citizen")
    assert _sensitive_answer("Are you a U.S. citizen?", p) == "Yes"


def test_refugee_and_asylum_flagged():
    assert _sensitive_answer("Are you a refugee?", _profile()) is FLAG
    assert _sensitive_answer("Were you granted asylum?", _profile()) is FLAG


def test_non_sensitive_returns_none():
    assert _sensitive_answer("Are you at least 18 years old?", _profile()) is None
    assert _sensitive_answer("Will you consent to a background check?", _profile()) is None


def test_grad_date_formats_current_degree():
    p = {"education": [
        {"end": "2017-05", "current": False},
        {"end": "2027-06", "current": True},
    ]}
    assert _grad_date(p) == "June 2027"


def test_grad_date_blank_when_no_end():
    assert _grad_date({"education": [{"current": True}]}) == ""
    assert _grad_date({}) == ""


def test_yes_no_and_work_auth_helpers():
    assert _yes_no("YES") == "Yes" and _yes_no("n") == "No" and _yes_no("maybe") is None
    assert _work_auth_answer("not authorized to work") == "No"
    assert _work_auth_answer("") is None


def test_work_auth_answer_handles_yaml_boolean():
    # YAML parses unquoted `Yes`/`No` as booleans; the mapper must still resolve them.
    assert _work_auth_answer(True) == "Yes"
    assert _work_auth_answer(False) == "No"
    assert _work_auth_answer("Yes") == "Yes"
    # free-text still works
    assert _work_auth_answer("Authorized to work in the US") == "Yes"
    assert _work_auth_answer("not authorized") == "No"


def test_sensitive_work_auth_from_boolean_profile():
    profile = {"sensitive": {"work_authorization": True}}
    assert _sensitive_answer("Are you legally authorized to work in the US?", profile) == "Yes"
