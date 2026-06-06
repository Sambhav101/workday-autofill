"""Minimal RAG: embed project docs into a numpy vector store, retrieve by cosine similarity.
Uses Ollama's embedding endpoint (nomic-embed-text) — no external dependencies beyond numpy.

    from src.agent.rag import build_index, search
    build_index()                    # one-time, saves to .rag_index.npz
    results = search("how does degree matching work", top_k=3)
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = PROJECT_ROOT / ".rag_index.npz"
CHUNKS_PATH = PROJECT_ROOT / ".rag_chunks.json"

DOCS_TO_INDEX = [
    "CLAUDE.md",
    "DESIGN.md",
    "README.md",
    "profile.yaml.example",
]

SRC_FILES = [
    "src/apply.py",
    "src/fill.py",
    "src/experience.py",
    "src/questions.py",
    "src/disclosures.py",
    "src/selfid.py",
    "src/signup.py",
    "src/widgets.py",
    "src/discover.py",
    "src/record.py",
    "src/resolver.py",
]


def _chunk_markdown(text: str, source: str, max_tokens: int = 500) -> list[dict]:
    sections = re.split(r'\n(?=#{1,4} )', text)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section or len(section) < 20:
            continue
        if len(section.split()) > max_tokens:
            paragraphs = section.split("\n\n")
            current = ""
            for p in paragraphs:
                if len((current + "\n\n" + p).split()) > max_tokens and current:
                    chunks.append({"text": current.strip(), "source": source})
                    current = p
                else:
                    current = current + "\n\n" + p if current else p
            if current.strip():
                chunks.append({"text": current.strip(), "source": source})
        else:
            chunks.append({"text": section, "source": source})
    return chunks


def _chunk_python(text: str, source: str) -> list[dict]:
    """Extract module docstring + function signatures as a single chunk."""
    lines = text.split("\n")
    docstring = ""
    in_doc = False
    for line in lines[:30]:
        if '"""' in line:
            if in_doc:
                docstring += line + "\n"
                break
            in_doc = True
        if in_doc:
            docstring += line + "\n"

    sigs = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("def ") and not stripped.startswith("def _"):
            sigs.append(stripped.split(":")[0])

    content = f"# {source}\n\n{docstring}\n\nPublic functions:\n" + "\n".join(sigs)
    return [{"text": content, "source": source}]


def _embed_texts(texts: list[str], host: str = "http://localhost:11434") -> np.ndarray:
    import requests
    embeddings = []
    for text in texts:
        resp = requests.post(
            f"{host}/api/embed",
            json={"model": "nomic-embed-text", "input": text},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings.append(data["embeddings"][0])
    return np.array(embeddings, dtype=np.float32)


def _content_hash() -> str:
    h = hashlib.md5()
    for f in DOCS_TO_INDEX + SRC_FILES:
        p = PROJECT_ROOT / f
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()


def build_index(host: str = "http://localhost:11434"):
    chunks = []
    for doc in DOCS_TO_INDEX:
        p = PROJECT_ROOT / doc
        if p.exists():
            chunks.extend(_chunk_markdown(p.read_text(), doc))

    for src in SRC_FILES:
        p = PROJECT_ROOT / src
        if p.exists():
            chunks.extend(_chunk_python(p.read_text(), src))

    # Add widget patterns from memory if available
    memory_dir = Path.home() / ".claude/projects/-Users-sambhav-projects-workday-autofill/memory"
    patterns = memory_dir / "workday-widget-patterns.md"
    if patterns.exists():
        chunks.extend(_chunk_markdown(patterns.read_text(), "widget-patterns"))

    texts = [c["text"] for c in chunks]
    embeddings = _embed_texts(texts, host)

    np.savez_compressed(INDEX_PATH, embeddings=embeddings)
    CHUNKS_PATH.write_text(json.dumps(chunks, indent=2))
    return len(chunks)


def _load_index() -> tuple[np.ndarray, list[dict]]:
    if not INDEX_PATH.exists() or not CHUNKS_PATH.exists():
        n = build_index()
        if n == 0:
            return np.array([]), []
    data = np.load(INDEX_PATH)
    chunks = json.loads(CHUNKS_PATH.read_text())
    return data["embeddings"], chunks


def search(query: str, top_k: int = 3, host: str = "http://localhost:11434") -> list[dict]:
    embeddings, chunks = _load_index()
    if len(chunks) == 0:
        return []

    q_emb = _embed_texts([query], host)[0]

    norms_e = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms_e = np.where(norms_e == 0, 1, norms_e)
    norm_q = np.linalg.norm(q_emb)
    if norm_q == 0:
        norm_q = 1
    similarities = (embeddings @ q_emb) / (norms_e.squeeze() * norm_q)

    top_indices = np.argsort(similarities)[::-1][:top_k]
    results = []
    for idx in top_indices:
        results.append({
            "source": chunks[idx]["source"],
            "text": chunks[idx]["text"][:500],
            "score": float(similarities[idx]),
        })
    return results
