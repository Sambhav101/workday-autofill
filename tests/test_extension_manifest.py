"""Guardrails for the Chrome extension's manifest — cheap checks that catch a
broken manifest (which Chrome would silently refuse to load) without a JS runner."""
import json
from pathlib import Path

EXT = Path(__file__).resolve().parent.parent / "extension"


def _manifest():
    return json.loads((EXT / "manifest.json").read_text())


def test_manifest_is_valid_json_mv3():
    m = _manifest()
    assert m["manifest_version"] == 3
    assert m["name"] and m["version"]


def test_action_popup_file_exists():
    m = _manifest()
    popup = m["action"]["default_popup"]
    assert (EXT / popup).is_file()


def test_referenced_script_exists():
    # popup.html references popup.js; make sure it's actually there.
    assert (EXT / "popup.js").is_file()
    assert "popup.js" in (EXT / "popup.html").read_text()


def test_minimal_permissions():
    m = _manifest()
    # activeTab + storage are all the popup needs; flag accidental scope creep.
    assert set(m["permissions"]) <= {"activeTab", "storage", "tabs"}
