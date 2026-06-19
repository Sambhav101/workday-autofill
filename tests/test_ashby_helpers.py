import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats import ashby

PROFILE = {
    "identity": {"first_name": "Sambhav", "last_name": "Shrestha",
                 "email": "sambhavshrestha111@gmail.com", "phone": "9293196443"},
    "contact": {"city": "Port Jefferson", "state": "NY"},
    "links": {"linkedin": "https://www.linkedin.com/in/sambhav101",
              "website": "https://sambhavshrestha.com",
              "github": "https://www.github.com/sambhav101"},
    "work_experience": [{"company": "HCL Technologies", "end": "2025-07", "current": False}],
}


def test_job_meta_with_application_suffix():
    m = ashby.ashby_job_meta("https://jobs.ashbyhq.com/voleon/e5c0863d-1371-4790-a50f-b467fa544b08/application")
    assert m["company"] == "voleon"
    assert m["tenant"] == "voleon"
    assert m["job_id"] == "e5c0863d-1371-4790-a50f-b467fa544b08"


def test_job_meta_without_suffix():
    m = ashby.ashby_job_meta("https://jobs.ashbyhq.com/openai/4a13c764")
    assert m["company"] == "openai"
    assert m["job_id"] == "4a13c764"


def test_field_value_known_labels():
    assert ashby.ashby_field_value("Email", PROFILE) == "sambhavshrestha111@gmail.com"
    assert ashby.ashby_field_value("Phone Number", PROFILE) == "9293196443"
    assert ashby.ashby_field_value("Current Company", PROFILE) == "HCL Technologies"
    assert ashby.ashby_field_value("Current Location", PROFILE) == "Port Jefferson, NY"
    assert ashby.ashby_field_value("LinkedIn", PROFILE) == "https://www.linkedin.com/in/sambhav101"
    assert ashby.ashby_field_value("GitHub", PROFILE) == "https://www.github.com/sambhav101"
    assert ashby.ashby_field_value("Portfolio", PROFILE) == "https://sambhavshrestha.com"
    assert ashby.ashby_field_value("Full Name", PROFILE) == "Sambhav Shrestha"


def test_field_value_unknown_label_returns_none():
    assert ashby.ashby_field_value("What is your favorite color?", PROFILE) is None
