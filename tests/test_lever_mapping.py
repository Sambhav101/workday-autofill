import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats import lever

PROFILE = {
    "identity": {"first_name": "Sambhav", "last_name": "Shrestha",
                 "email": "sambhavshrestha111@gmail.com", "phone": "9293196443"},
    "contact": {"city": "Port Jefferson", "state": "NY"},
    "links": {"linkedin": "https://www.linkedin.com/in/sambhav101",
              "website": "https://sambhavshrestha.com",
              "github": "https://www.github.com/sambhav101"},
    "work_experience": [
        {"company": "HCL Technologies", "end": "2025-07", "current": False},
        {"company": "Amazon", "end": "2023-03", "current": False},
    ],
}


def test_full_name():
    assert lever.full_name(PROFILE) == "Sambhav Shrestha"


def test_current_company_picks_latest_end():
    assert lever.current_company(PROFILE) == "HCL Technologies"


def test_standard_field_values():
    vals = lever.standard_field_values(PROFILE)
    assert vals["name"] == "Sambhav Shrestha"
    assert vals["email"] == "sambhavshrestha111@gmail.com"
    assert vals["phone"] == "9293196443"
    assert vals["location"] == "Port Jefferson, NY"
    assert vals["org"] == "HCL Technologies"
    assert vals["urls[LinkedIn]"] == "https://www.linkedin.com/in/sambhav101"
    assert vals["urls[GitHub]"] == "https://www.github.com/sambhav101"
    assert vals["urls[Portfolio]"] == "https://sambhavshrestha.com"


def test_standard_field_values_omits_empty():
    vals = lever.standard_field_values({"identity": {"first_name": "A", "last_name": "B"}})
    assert "email" not in vals
    assert "urls[LinkedIn]" not in vals
    assert vals["name"] == "A B"
