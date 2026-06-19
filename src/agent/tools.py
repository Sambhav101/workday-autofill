"""Tool registry for the agent. Each tool wraps an existing pipeline function
with a JSON-schema description the LLM can understand and call."""
from __future__ import annotations

import json
import traceback
from typing import Any

from playwright.sync_api import sync_playwright, Page

_browser = None
_page: Page | None = None


def _get_page() -> Page:
    global _browser, _page
    if _page and not _page.is_closed():
        return _page
    from .. import browser
    pw = sync_playwright().start()
    _browser = browser.connect(pw)
    _page = browser.find_any_tab(_browser)
    if not _page:
        raise RuntimeError("No Chrome tab available. Launch Chrome with scripts/launch_chrome.sh first.")
    return _page


def _cleanup():
    global _browser, _page
    if _browser:
        try:
            _browser.close()
        except Exception:
            pass
    _browser = None
    _page = None


# ── tool implementations ───────────────────────────────────────────────────

def _apply_to_job(url: str) -> dict:
    from ..ats import dispatch
    page = _get_page()
    return dispatch(page, url, auto_submit=True).to_dict()


def _apply_batch(urls: list[str]) -> list[dict]:
    from ..ats import run_batch
    return [r.to_dict() for r in run_batch(urls, auto_submit=True)]


def _check_page() -> dict:
    from ..discover import discover_page, discover_fields
    from ..apply import detect
    page = _get_page()
    kind = detect(page)
    tree = discover_page(page)
    fields = discover_fields(page)
    visible = [f for f in fields if f.get("visible")]
    required_empty = []
    placeholders = {"select one", "—", "--", ""}
    for f in visible:
        if f.get("required"):
            val = (f.get("value") or "").strip().lower()
            if val in placeholders:
                required_empty.append(f.get("label") or f.get("aid", "unknown"))
    return {
        "page_type": kind,
        "url": page.url[:150],
        "total_fields": len(visible),
        "unfilled": tree["unfilled_count"],
        "required_empty": required_empty,
        "fields": [
            {"label": f.get("label", ""), "widget": f["widget"],
             "value": (f.get("value") or "")[:50], "required": f.get("required", False)}
            for f in visible[:20]
        ],
    }


def _fill_current_page() -> dict:
    from ..apply import detect, FILLERS, _check_required_fields
    page = _get_page()
    kind = detect(page)
    if kind in FILLERS:
        FILLERS[kind](page)
    missing = _check_required_fields(page)
    return {"page_type": kind, "filled": True, "required_still_empty": missing}


def _click_next() -> dict:
    from ..apply import _click_next as do_click, detect, _check_required_fields
    page = _get_page()
    missing = _check_required_fields(page)
    if missing:
        return {"clicked": False, "reason": f"Required fields empty: {missing}"}
    ok = do_click(page)
    if not ok:
        return {"clicked": False, "reason": "No Next button found"}
    page.wait_for_timeout(2000)
    errs = page.locator('[data-automation-id="errorMessage"]')
    if errs.count():
        err_texts = [errs.nth(i).inner_text()[:120] for i in range(min(errs.count(), 5))]
        return {"clicked": True, "errors": err_texts, "page_type": detect(page)}
    return {"clicked": True, "page_type": detect(page)}


def _list_applications() -> list[dict]:
    from ..record import _load
    entries = _load()
    return [{"company": e.get("company", ""), "title": e.get("title", ""),
             "job_id": e.get("job_id", ""), "status": e.get("status", ""),
             "date": e.get("submitted_at", "")} for e in entries[-15:]]


def _run_signup() -> dict:
    from ..signup import create_or_sign_in
    from ..profile import load_profile
    page = _get_page()
    profile = load_profile()
    result = create_or_sign_in(page, profile, auto_email=False)
    return {"result": result, "url": page.url[:150]}


def _search_codebase(query: str) -> list[dict]:
    try:
        from .rag import search
        return search(query, top_k=3)
    except Exception as e:
        return [{"error": str(e)}]


# ── tool definitions (JSON schema for LLM) ────────────────────────────────

TOOLS = [
    {
        "name": "apply_to_job",
        "description": "Apply to a single Workday job. Navigates to the URL, fills all pages, and submits. Returns status (submitted/blocked/skipped/error) and reason.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full Workday job URL"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "apply_batch",
        "description": "Apply to multiple Workday jobs in sequence. Each job is independent — blockers are logged and the pipeline moves to the next job.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "description": "List of Workday job URLs"}
            },
            "required": ["urls"],
        },
    },
    {
        "name": "check_page",
        "description": "Inspect the current browser page: detect page type, list visible fields, show which required fields are empty. Use this to understand what's on screen before taking action.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "fill_current_page",
        "description": "Fill all fields on the current page using profile data. Does NOT click Next — use click_next after verifying required fields.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "click_next",
        "description": "Check required fields, then click Next/Save & Continue. Will refuse if required fields are still empty. Returns the new page type after navigation.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_applications",
        "description": "Show recently submitted applications from the tracker (applications.yaml). Use to check if a job was already applied to.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "run_signup",
        "description": "Handle account creation or sign-in on the current Workday tenant. If email verification is needed, it will pause and ask the user.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "search_codebase",
        "description": "Search project documentation and code patterns for context. Use when you need to understand how something works or debug an error.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"}
            },
            "required": ["query"],
        },
    },
]

_DISPATCH = {
    "apply_to_job": lambda args: _apply_to_job(args["url"]),
    "apply_batch": lambda args: _apply_batch(args["urls"]),
    "check_page": lambda args: _check_page(),
    "fill_current_page": lambda args: _fill_current_page(),
    "click_next": lambda args: _click_next(),
    "list_applications": lambda args: _list_applications(),
    "run_signup": lambda args: _run_signup(),
    "search_codebase": lambda args: _search_codebase(args["query"]),
}


def execute(name: str, arguments: dict[str, Any]) -> str:
    fn = _DISPATCH.get(name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = fn(arguments)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()[-500:]})


def tool_schemas_ollama() -> list[dict]:
    """Return tool definitions in Ollama's tool-use format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in TOOLS
    ]


def tool_schemas_anthropic() -> list[dict]:
    """Return tool definitions in Anthropic's tool-use format."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in TOOLS
    ]
