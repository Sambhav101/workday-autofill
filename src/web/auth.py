"""LAN-access auth for the web UI.

When the UI binds to a non-loopback interface, the queue API can drive a
logged-in browser session — so anyone on the LAN could otherwise control it.
We gate ``/api/*`` behind a shared token. Localhost-only runs need no token.

The active token is carried to the app via the ``WORKDAY_TOKEN`` env var so
``uvicorn``'s string-import of the app can pick it up. Empty/unset = no auth.
"""
from __future__ import annotations

import os
import secrets
import socket

ENV_VAR = "WORKDAY_TOKEN"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

# The page and its assets are harmless on their own; the token gates the API
# the page talks to, so we serve these without a token.
PUBLIC_PREFIXES = ("/static",)
PUBLIC_PATHS = {"/", "/favicon.ico"}


def resolve_token(host: str, explicit: str | None, no_auth: bool) -> str | None:
    """Decide the active token at startup.

    - ``no_auth`` -> always off.
    - explicit token (flag) or ``WORKDAY_TOKEN`` env -> use it.
    - exposed host (not loopback) with no token -> auto-generate one.
    - localhost-only -> off.
    """
    if no_auth:
        return None
    token = explicit or os.environ.get(ENV_VAR) or None
    if token:
        return token
    if host not in LOCAL_HOSTS:
        return secrets.token_urlsafe(16)
    return None


def is_public(path: str) -> bool:
    """True if ``path`` may be served without a token."""
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(p) for p in PUBLIC_PREFIXES)


def request_token(headers, query_params) -> str | None:
    """Pull the token from a request: ``X-Auth-Token`` header, then ``?token=``.

    The query-param fallback exists because ``EventSource`` (SSE) can't set
    custom headers.
    """
    return headers.get("x-auth-token") or query_params.get("token")


def lan_ip() -> str | None:
    """Best-effort LAN IP via a dummy UDP socket (no packets are actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
