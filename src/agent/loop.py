"""Agent loop with dual backend support: Ollama (free/local) and Claude API (cheap).
Both use the same tools and system prompt. No framework dependencies.

    ./venv/bin/python -m src.agent                    # default backend from config
    ./venv/bin/python -m src.agent --backend ollama   # force Ollama
    ./venv/bin/python -m src.agent --backend claude   # force Claude API
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from . import tools

console = Console()

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "agent_config.yaml"

SYSTEM_PROMPT = """\
You are a Workday job application assistant. You help the user apply to jobs on Workday \
by using the tools available to you.

## How you work
- The user gives you Workday job URLs. You call `apply_to_job` to fill and submit each one.
- For multiple URLs, use `apply_batch` for efficiency.
- Before applying, check `list_applications` to avoid duplicates.
- If a job is blocked, report the reason and move on — don't retry endlessly.
- If email verification or password reset is needed, tell the user and wait for their input.

## Rules
- NEVER handle email verification or password resets yourself. Always ask the user.
- Check required fields before clicking Next.
- Fill all sections (work, education, skills) even if marked optional.
- Education: degree must be MS/BS only (no arts, engineering, tech).
- No blind first-option fallbacks — return failure instead of guessing.
- Report results clearly: what was submitted, what was blocked, and why.

## When errors occur
- Use `check_page` to see current page state.
- Use `fill_current_page` + `click_next` for manual step-through.
- Use `search_codebase` to understand how the pipeline handles specific cases.
- If stuck, describe the error to the user and suggest manual intervention.

Keep responses concise. State what you did and what happened — no filler.\
"""


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    return {}


# ── Ollama backend ─────────────────────────────────────────────────────────

def _ollama_chat(messages: list[dict], config: dict) -> dict:
    import requests
    host = config.get("ollama_host", "http://localhost:11434")
    model = config.get("ollama_model", "llama3.1:8b")
    resp = requests.post(
        f"{host}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "tools": tools.tool_schemas_ollama(),
            "stream": False,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def _run_ollama(config: dict):
    model = config.get("ollama_model", "llama3.1:8b")
    console.print(f"[bold]Workday Agent[/bold] (Ollama: {model})")
    console.print("[dim]Type a job URL, a command, or 'quit' to exit.[/dim]\n")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user_input = console.input("[bold cyan]> [/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            break

        messages.append({"role": "user", "content": user_input})

        while True:
            try:
                resp = _ollama_chat(messages, config)
            except Exception as e:
                console.print(f"[red]Ollama error: {e}[/red]")
                break

            msg = resp.get("message", {})
            messages.append(msg)

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                text = msg.get("content", "")
                if text:
                    console.print(f"\n{text}\n")
                break

            for tc in tool_calls:
                fn = tc["function"]
                name = fn["name"]
                args = fn.get("arguments", {})
                console.print(f"[dim]  → {name}({json.dumps(args, default=str)[:100]})[/dim]")
                result = tools.execute(name, args)
                messages.append({"role": "tool", "content": result})
                _print_tool_result(name, result)


# ── Claude API backend ─────────────────────────────────────────────────────

def _run_claude(config: dict):
    import anthropic
    model = config.get("claude_model", "claude-sonnet-4-6")
    client = anthropic.Anthropic()
    console.print(f"[bold]Workday Agent[/bold] (Claude API: {model})")
    console.print("[dim]Type a job URL, a command, or 'quit' to exit.[/dim]\n")

    messages: list[dict] = []
    total_input = 0
    total_output = 0

    while True:
        try:
            user_input = console.input("[bold cyan]> [/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            break

        messages.append({"role": "user", "content": user_input})

        while True:
            try:
                resp = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=tools.tool_schemas_anthropic(),
                    messages=messages,
                )
            except Exception as e:
                console.print(f"[red]Claude API error: {e}[/red]")
                break

            total_input += resp.usage.input_tokens
            total_output += resp.usage.output_tokens

            assistant_content = resp.content
            messages.append({"role": "assistant", "content": assistant_content})

            if resp.stop_reason != "tool_use":
                for block in assistant_content:
                    if hasattr(block, "text") and block.text:
                        console.print(f"\n{block.text}\n")
                console.print(f"[dim]  tokens: {total_input:,} in / {total_output:,} out[/dim]")
                break

            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    name = block.name
                    args = block.input
                    console.print(f"[dim]  → {name}({json.dumps(args, default=str)[:100]})[/dim]")
                    result = tools.execute(name, args)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                    _print_tool_result(name, result)

            messages.append({"role": "user", "content": tool_results})


# ── shared helpers ─────────────────────────────────────────────────────────

def _print_tool_result(name: str, result_json: str):
    try:
        data = json.loads(result_json)
    except Exception:
        return
    if "error" in data:
        console.print(f"[red]  ✗ {name}: {data['error'][:120]}[/red]")
        return
    status = data.get("status")
    if status:
        color = {"submitted": "green", "skipped": "dim", "blocked": "yellow",
                 "review": "cyan", "error": "red"}.get(status, "white")
        title = data.get("title", "")
        reason = data.get("reason", "")
        console.print(f"[{color}]  {status}: {title} — {reason[:80]}[/{color}]")


def run(backend: str | None = None):
    config = _load_config()
    backend = backend or config.get("agent_backend", "ollama")

    if backend == "claude":
        _run_claude(config)
    elif backend == "ollama":
        _run_ollama(config)
    else:
        console.print(f"[red]Unknown backend: {backend}. Use 'ollama' or 'claude'.[/red]")
        return

    tools._cleanup()
    console.print("[dim]Agent stopped.[/dim]")
