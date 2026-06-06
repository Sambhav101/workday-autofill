"""Entry point: python -m src.web [--port 8000]"""
import argparse
import uvicorn

ap = argparse.ArgumentParser(description="Workday Autofill Web UI")
ap.add_argument("--port", type=int, default=8000)
ap.add_argument("--host", default="127.0.0.1")
args = ap.parse_args()

uvicorn.run("src.web.app:app", host=args.host, port=args.port, reload=False)
