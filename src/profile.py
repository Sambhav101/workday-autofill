"""Load and access the canonical profile.yaml."""
from __future__ import annotations

from pathlib import Path
import yaml

PROFILE_PATH = Path(__file__).resolve().parent.parent / "profile.yaml"


def load_profile(path: Path = PROFILE_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy profile.yaml.example and fill it in."
        )
    with open(path) as f:
        return yaml.safe_load(f)
