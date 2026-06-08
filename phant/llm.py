"""
phant/llm.py — PHANT's language interface.

This is the ONLY place PHANT talks to a language model. It reuses the same
DeepSeek integration and the single shared DEEPSEEK_API_KEY already used by
ai_engine.py / ai_copilot.py. PHANG owns AI — PHANT does not stand up its own
provider, model, or key.

Architectural reminder: the LLM is the INTERFACE layer, not the intelligence
layer. PHANT assembles structured context (memories, decisions, constraints,
divergences, ecosystem snapshot); the model renders it into language. If the
model is unavailable, the cognition substrate (this whole package's data) is
still valuable and queryable — only language generation degrades.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger("phant.llm")

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL   = "deepseek-chat"

# Embeddings are optional in V1 ("store but unused"). If an embeddings provider is
# configured we generate vectors at memory-creation time so the column is populated
# from day one; if not, memories are stored without vectors and nothing breaks.
OPENAI_API_URL    = "https://api.openai.com/v1/embeddings"
EMBEDDING_MODEL   = os.getenv("PHANT_EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM     = 1536


def _deepseek_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


async def complete(
    system: str,
    user: str,
    *,
    json_mode: bool = False,
    max_tokens: int = 900,
    temperature: float = 0.3,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Single-turn (or short-history) completion. Returns raw text.
    On any failure returns an empty string — callers must degrade gracefully.
    """
    key = _deepseek_key()
    if not key:
        log.warning("DEEPSEEK_API_KEY not set — PHANT language layer disabled")
        return ""

    messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user})

    payload: Dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        log.error("DeepSeek HTTP %s: %s", e.response.status_code, e.response.text[:200])
        return ""
    except Exception as e:  # noqa: BLE001
        log.error("DeepSeek call failed: %s", e)
        return ""


async def complete_json(
    system: str,
    user: str,
    *,
    max_tokens: int = 1200,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """Completion that must return a JSON object. Returns {} on failure."""
    raw = await complete(
        system, user, json_mode=True, max_tokens=max_tokens, temperature=temperature
    )
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("PHANT LLM returned non-JSON: %s", raw[:160])
        return {}


async def embed(text: str) -> Optional[List[float]]:
    """
    Best-effort embedding generation. Returns a 1536-d vector or None.

    V1 stores embeddings but does not query them, so None is perfectly fine — the
    `embedding` column simply stays NULL for that row until vector search is
    activated. We only call out if OPENAI_API_KEY is configured (DeepSeek does not
    currently expose an embeddings endpoint).
    """
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or not text:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                OPENAI_API_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": EMBEDDING_MODEL, "input": text[:8000]},
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
    except Exception as e:  # noqa: BLE001
        log.warning("Embedding generation skipped: %s", e)
        return None
