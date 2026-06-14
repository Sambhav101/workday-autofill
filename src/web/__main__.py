"""Entry point: python -m src.web [--port 8000] [--host 0.0.0.0]

Binds to all interfaces by default so you can add URLs from another device on
the LAN (e.g. a Mac) while the agent runs on the Windows/GPU box. When exposed
this way, the queue API is gated behind a token (auto-generated unless you pass
--token or --no-auth). See issue #1.
"""
import argparse
import os

import uvicorn

from src.web import auth

ap = argparse.ArgumentParser(description="Workday Autofill Web UI")
ap.add_argument("--port", type=int, default=8000)
ap.add_argument("--host", default="0.0.0.0",
                help="Interface to bind. Default 0.0.0.0 (LAN). Use 127.0.0.1 for local-only.")
ap.add_argument("--token", default=None,
                help="Shared auth token for the API. Auto-generated when exposed if omitted.")
ap.add_argument("--no-auth", action="store_true",
                help="Disable the auth token even when exposed on the LAN. Not recommended.")
args = ap.parse_args()

token = auth.resolve_token(args.host, args.token, args.no_auth)
if token:
    os.environ[auth.ENV_VAR] = token


def _print_banner():
    local = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    suffix = f"?token={token}" if token else ""
    lines = ["", "  Workday Autofill UI", f"  → Local:   http://{local}:{args.port}/{suffix}"]
    if args.host not in auth.LOCAL_HOSTS:
        ip = auth.lan_ip()
        lines.append(f"  → Network: http://{ip}:{args.port}/{suffix}" if ip
                     else "  → Network: (could not determine LAN IP)")
    if token:
        lines += [f"\n  Auth token: {token}",
                  "  Open the Network URL above (token is embedded) on your other device."]
    elif args.host not in auth.LOCAL_HOSTS:
        lines.append("\n  WARNING: auth disabled while exposed on the LAN — anyone on this "
                     "network can drive your browser session.")
    print("\n".join(lines) + "\n", flush=True)


_print_banner()
uvicorn.run("src.web.app:app", host=args.host, port=args.port, reload=False)
