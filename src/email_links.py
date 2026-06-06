"""Read Workday verification/reset emails from the burner Gmail via the MCP
Gmail connector. Extracts the action link (verify account, reset password) so
the signup flow can open it automatically instead of pausing for the user.

This module is called by signup.py — it doesn't run standalone. The Gmail
connector must be authenticated before use (run /mcp → claude.ai Gmail).
"""
from __future__ import annotations

import re
import time


def find_workday_link(gmail_search, gmail_get_thread, *, tenant: str,
                      kind: str = "any", max_wait_s: int = 90,
                      poll_interval_s: int = 10) -> str | None:
    """Poll the burner Gmail for a Workday email matching `tenant` and return
    the action link (verify / reset). Returns None if nothing arrives in time.

    kind: "verify", "reset", or "any" (matches either).
    """
    deadline = time.monotonic() + max_wait_s
    seen_ids: set[str] = set()

    # build a query scoped to this tenant
    tenant_short = tenant.split(".")[0]  # e.g. "nvidia" from "nvidia.wd5.myworkdayjobs.com"
    query = f"from:{tenant_short} newer_than:1d"

    while time.monotonic() < deadline:
        try:
            result = gmail_search(query=query, pageSize=10)
        except Exception:  # noqa: BLE001
            time.sleep(poll_interval_s)
            continue

        threads = result.get("threads", []) if isinstance(result, dict) else []
        for thread in threads:
            tid = thread.get("id", "")
            if tid in seen_ids:
                continue
            seen_ids.add(tid)

            # check snippet for relevance
            for msg in thread.get("messages", []):
                snippet = (msg.get("snippet", "") + " " + msg.get("subject", "")).lower()
                if kind == "verify" and "verify" not in snippet and "confirm" not in snippet:
                    continue
                if kind == "reset" and "reset" not in snippet:
                    continue
                if tenant_short.lower() not in snippet and tenant not in snippet:
                    continue

                # fetch full thread to get the link
                try:
                    full = gmail_get_thread(threadId=tid, messageFormat="FULL_CONTENT")
                except Exception:  # noqa: BLE001
                    continue

                link = _extract_link(full, tenant)
                if link:
                    return link

        time.sleep(poll_interval_s)

    return None


def _extract_link(thread_data, tenant: str) -> str | None:
    """Pull the first Workday action URL from a thread's message bodies."""
    tenant_short = tenant.split(".")[0]
    messages = []
    if isinstance(thread_data, dict):
        messages = thread_data.get("messages", [])

    for msg in messages:
        body = msg.get("plaintext_body", "") or msg.get("snippet", "")
        # look for URLs containing the tenant
        urls = re.findall(r'https?://[^\s<>"\']+', body)
        for url in urls:
            if tenant_short in url and ("passwordreset" in url or "verifyaccount" in url
                                         or "verify" in url or "confirm" in url
                                         or "createaccount" in url):
                return url.rstrip(".")
        # fallback: any URL with the tenant domain
        for url in urls:
            if tenant in url or tenant_short in url:
                return url.rstrip(".")

    return None
