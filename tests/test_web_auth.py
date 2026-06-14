"""Tests for LAN-access auth: token resolution + the /api gate."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.web import auth  # noqa: E402


# --- resolve_token ---------------------------------------------------------

def test_localhost_needs_no_token():
    assert auth.resolve_token("127.0.0.1", None, no_auth=False) is None
    assert auth.resolve_token("localhost", None, no_auth=False) is None


def test_exposed_host_autogenerates_token():
    t = auth.resolve_token("0.0.0.0", None, no_auth=False)
    assert t and len(t) >= 16


def test_explicit_token_wins_even_on_localhost():
    assert auth.resolve_token("127.0.0.1", "sekret", no_auth=False) == "sekret"


def test_env_token_used_when_no_flag(monkeypatch):
    monkeypatch.setenv(auth.ENV_VAR, "fromenv")
    assert auth.resolve_token("0.0.0.0", None, no_auth=False) == "fromenv"


def test_no_auth_disables_even_when_exposed(monkeypatch):
    monkeypatch.setenv(auth.ENV_VAR, "fromenv")
    assert auth.resolve_token("0.0.0.0", "explicit", no_auth=True) is None


# --- is_public -------------------------------------------------------------

def test_index_and_static_are_public():
    assert auth.is_public("/")
    assert auth.is_public("/static/app.js")
    assert auth.is_public("/favicon.ico")


def test_api_paths_are_not_public():
    assert not auth.is_public("/api/queue")
    assert not auth.is_public("/api/run")


# --- middleware via the real app ------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv(auth.ENV_VAR, "testtoken")
    from fastapi.testclient import TestClient

    from src.web.app import app
    return TestClient(app)


def test_index_loads_without_token(client):
    assert client.get("/").status_code == 200


def test_api_rejected_without_token(client):
    assert client.get("/api/queue").status_code == 401


def test_api_accepts_header_token(client):
    r = client.get("/api/queue", headers={"X-Auth-Token": "testtoken"})
    assert r.status_code == 200


def test_api_accepts_query_token(client):
    # EventSource can't set headers, so ?token= must work too.
    assert client.get("/api/queue?token=testtoken").status_code == 200


def test_api_rejects_wrong_token(client):
    assert client.get("/api/queue", headers={"X-Auth-Token": "nope"}).status_code == 401
