"""Entry point: python -m src.agent [--backend ollama|claude]"""
import argparse
from .loop import run

ap = argparse.ArgumentParser(description="Workday application agent")
ap.add_argument("--backend", choices=["ollama", "claude"],
                help="LLM backend (default: from agent_config.yaml or ollama)")
args = ap.parse_args()
run(backend=args.backend)
