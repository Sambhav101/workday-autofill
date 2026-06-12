"""Interactive profile setup.

Run `python -m src.setup` to generate a personal `profile.yaml` by answering
prompts. The file is gitignored, so your details never enter the repo.

Sensitive EEO fields (gender, race, veteran, disability) are left blank — they
are never prompted-and-guessed. Edit profile.yaml later if you choose to share them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from .profile import PROFILE_PATH


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        val = ""
    return val or default


def ask_bool(prompt: str, default: bool = False) -> bool:
    d = "Y/n" if default else "y/N"
    val = ask(f"{prompt} ({d})").lower()
    if not val:
        return default
    return val in ("y", "yes", "true", "1")


def ask_list(prompt: str) -> list[str]:
    """Comma-separated input -> list of trimmed, non-empty strings."""
    raw = ask(prompt)
    return [s.strip() for s in raw.split(",") if s.strip()]


def collect_work() -> list[dict]:
    jobs: list[dict] = []
    print("\n── Work experience ──")
    while ask_bool(f"Add a work experience (#{len(jobs) + 1})?", default=(len(jobs) == 0)):
        company = ask("  Company")
        if not company:
            break
        job = {
            "company": company,
            "title": ask("  Job title"),
            "location": ask("  Location (City, State, Country)"),
            "start": ask("  Start (YYYY-MM)"),
            "end": ask("  End (YYYY-MM, blank if current)"),
            "current": ask_bool("  Current role?", default=False),
            "bullets": ask_list("  Bullet points (comma-separated)"),
        }
        jobs.append(job)
    return jobs


def collect_education() -> list[dict]:
    schools: list[dict] = []
    print("\n── Education ──")
    while ask_bool(f"Add an education entry (#{len(schools) + 1})?", default=(len(schools) == 0)):
        school = ask("  School name")
        if not school:
            break
        entry = {
            "school": school,
            "degree": ask("  Degree (e.g. Master's, Bachelor's)"),
            "field": ask("  Field of study"),
            "gpa": ask("  GPA (optional)"),
            "start": ask("  Start (YYYY-MM)"),
            "end": ask("  End (YYYY-MM)"),
            "current": ask_bool("  Currently enrolled?", default=False),
        }
        # Optional Workday-list overrides — only included if provided.
        search_term = ask("  Workday search term (optional, blank = derive from name)")
        if search_term:
            entry["search_term"] = search_term
        workday_name = ask("  Exact Workday school name (optional)")
        if workday_name:
            entry["workday_name"] = workday_name
        schools.append(entry)
    return schools


def build_profile() -> dict:
    print("This will create your profile.yaml. Press Enter to accept a default.\n")
    print("── Identity ──")
    first = ask("First name")
    last = ask("Last name")
    profile = {
        "identity": {
            "first_name": first,
            "last_name": last,
            "preferred_name": ask("Preferred name", default=first),
            "email": ask("Email"),
            "phone": ask("Phone"),
        },
        "contact": {
            "address_line1": ask("\n── Contact ──\nStreet address"),
            "city": ask("City"),
            "state": ask("State / province"),
            "postal_code": ask("Postal code"),
            "country": ask("Country", default="United States"),
        },
        "links": {
            "linkedin": ask("\n── Links ──\nLinkedIn URL"),
            "website": ask("Website URL"),
            "github": ask("GitHub URL"),
        },
        "resume_path": ask("\nPath to your resume PDF"),
        "work_experience": collect_work(),
        "education": collect_education(),
        "skills": {
            "languages": ask_list("\n── Skills ──\nProgramming languages (comma-separated)"),
            "ml_ai": ask_list("ML/AI skills (comma-separated)"),
            "cloud_tools": ask_list("Cloud / tools (comma-separated)"),
        },
        "sensitive": {
            "work_authorization": ask("\n── Work eligibility ──\nWork authorization (e.g. 'Authorized to work in the US')"),
            "requires_sponsorship": ask("Requires visa sponsorship? (Yes/No)"),
            # EEO fields intentionally blank — edit profile.yaml to set them.
            "gender": "",
            "race_ethnicity": "",
            "veteran_status": "",
            "disability_status": "",
            "hispanic_latino": "",
        },
        "preferences": {
            "how_did_you_hear": ask("\n── Preferences ──\nHow did you hear about us?", default="Company website"),
            "desired_salary": ask("Desired salary (optional)"),
            "willing_to_relocate": ask("Willing to relocate? (Yes/No)"),
            "earliest_start_date": ask("Earliest start date (optional)"),
        },
    }
    return profile


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate profile.yaml interactively.")
    ap.add_argument("--output", type=Path, default=PROFILE_PATH, help="where to write the profile")
    ap.add_argument("--force", action="store_true", help="overwrite an existing profile")
    args = ap.parse_args()

    if args.output.exists() and not args.force:
        print(f"{args.output} already exists. Re-run with --force to overwrite, "
              "or edit it directly.", file=sys.stderr)
        return 1

    profile = build_profile()

    resume = profile.get("resume_path")
    if resume and not Path(resume).expanduser().exists():
        print(f"\nWarning: resume not found at {resume} — fix resume_path in "
              f"{args.output.name} before uploading.")

    with open(args.output, "w") as f:
        f.write("# Generated by `python -m src.setup`. Gitignored — safe to edit.\n")
        f.write("# Sensitive EEO fields are blank by design; set them yourself if you wish.\n\n")
        yaml.safe_dump(profile, f, sort_keys=False, allow_unicode=True, default_flow_style=False)

    print(f"\nWrote {args.output}. Review it, then run: python -m src.fill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
