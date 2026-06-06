"""FastAPI web app for the Workday agent.

    ./venv/bin/python -m src.web
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from ..record import _load as load_applications
from . import queue as Q
from . import runner

app = FastAPI(title="Workday Autofill")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


@app.post("/api/queue/add")
async def add_to_queue(request: Request):
    body = await request.json()
    urls = body.get("urls", [])
    if isinstance(urls, str):
        urls = [u.strip() for u in urls.split("\n") if u.strip()]
    added = Q.add_urls(urls)
    return {"added": added, "total_queued": len(Q.get_queued())}


@app.get("/api/queue")
async def get_queue():
    return Q.get_all()


@app.post("/api/queue/clear")
async def clear_queue():
    Q.clear_all()
    return {"cleared": True}


@app.post("/api/queue/clear-done")
async def clear_done():
    Q.remove_completed()
    return {"cleared": True}


@app.post("/api/run")
async def run_agent(request: Request):
    body = await request.json()
    auto_submit = body.get("auto_submit", True)
    backend = body.get("backend", "direct")
    if runner.is_running():
        return JSONResponse({"error": "Agent is already running"}, status_code=409)
    runner.run_queue(backend=backend, auto_submit=auto_submit)
    return {"started": True}


@app.post("/api/stop")
async def stop_agent():
    runner.stop()
    return {"stopped": True}


@app.get("/api/status")
async def get_status():
    return {
        "running": runner.is_running(),
        "queued": len(Q.get_queued()),
        "queue": Q.get_all(),
    }


@app.get("/api/applications")
async def get_applications():
    return load_applications()


@app.get("/api/events")
async def events(request: Request):
    async def event_stream():
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def on_message(msg: str):
            loop.call_soon_threadsafe(q.put_nowait, msg)

        runner.add_listener(on_message)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30)
                    yield {"data": msg}
                except asyncio.TimeoutError:
                    yield {"data": json.dumps({"event": "ping"})}
        finally:
            runner.remove_listener(on_message)

    return EventSourceResponse(event_stream())
