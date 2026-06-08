"""
phant/services/chat_service.py — the elephant-button doorway.

Two question modes, one answer surface:

    LIVE QUERY       — "What's happening now?" routes through ecosystem_service
                       to read current product execution state in real time.
                       Keywords: show, current, now, today, how many, status, open.

    INTELLIGENCE     — "What do I know / what should I do?" routes through the
    QUERY              PHANT memory+decision+constraint+divergence corpus.
                       Keywords: think, know, believe, decision, remember, last time,
                       pattern, trend, why, should, recommendation.

The router is a weighted keyword heuristic (V1). V2 will use an intent classifier.

Sessions are persisted (PhantSession.transcript). Each call either continues the
open session for the context or opens a new one. The last 6 turns are injected
into the LLM history; older turns are summarised on session close.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from ..repositories import (
    ConstraintRepository,
    DivergenceRepository,
    MemoryRepository,
    SessionRepository,
)
from ..services.ecosystem_service import snapshot, snapshot_text
from .. import llm

log = logging.getLogger("phant.chat")

# ── System prompts ────────────────────────────────────────────────────────────────

_SYSTEM_BASE = """\
You are PHANT — the intelligence layer above the PHANG ecosystem built by
Boluwatife Faturoti (solo founder, AI-native infrastructure company, Lagos).

You are NOT a general-purpose assistant. You are the founder's intelligence system.
Your job: reason across the founder's products, memory, decisions, and constraints
to help him make better decisions and see patterns he might miss.

Rules:
- No emoji. No filler phrases. No "certainly" or "great question".
- Be direct. Use numbers when you have them.
- When you are uncertain, say so explicitly. Do not confabulate data.
- When you recommend an action, state the reasoning concisely.
- Tone: enterprise, direct, no cheerleading.
- If the question is outside your data (you have no memories, no product state),
  say "I don't have data on that" — do not invent an answer.
- Max response length: 300 words unless a detailed breakdown is explicitly requested.
"""

_LIVE_SYSTEM = _SYSTEM_BASE + "\n\nYou have access to the current product execution state below."
_INTEL_SYSTEM = _SYSTEM_BASE + "\n\nYou have access to the founder's memory corpus, decisions, constraints, and divergences below."


# ── Live-Query keyword signals ────────────────────────────────────────────────────

_LIVE_KEYWORDS = {
    "show", "current", "now", "today", "status", "open", "pending", "active",
    "how many", "what is", "what are", "count", "total", "overview", "dashboard",
    "running", "live", "right now", "at the moment", "this week",
}

_INTEL_KEYWORDS = {
    "think", "know", "believe", "remember", "recall", "decision", "decided",
    "last time", "before", "pattern", "trend", "why", "should", "recommend",
    "advice", "history", "learn", "taught", "risk", "goal", "commitment",
    "constraint", "rule", "principle", "belief", "concern", "worry",
}


def _route(message: str) -> str:
    """
    Return "live" or "intel" based on keyword weight. Live wins ties.
    The threshold is intentionally loose — wrong mode is recoverable; missing
    context is not.
    """
    lower = message.lower()
    live_score  = sum(1 for kw in _LIVE_KEYWORDS  if kw in lower)
    intel_score = sum(1 for kw in _INTEL_KEYWORDS if kw in lower)

    if intel_score > live_score + 1:
        return "intel"
    return "live"


# ── Context builders ──────────────────────────────────────────────────────────────

def _build_live_context(db: DBSession, owner_user_id: int) -> str:
    snap = snapshot(db, owner_user_id, is_founder=True)
    return snapshot_text(snap)


def _build_intel_context(
    db: DBSession,
    owner_user_id: int,
    message: str,
    limit: int = 12,
) -> str:
    # Search: keyword match in content (V1). V2 will use vector search.
    words = [w for w in message.lower().split() if len(w) > 3][:8]
    search_term = words[0] if words else None

    mrepo = MemoryRepository(db)
    memories = mrepo.query(
        owner_user_id,
        search=search_term,
        limit=limit,
        status="active",
    )
    if len(memories) < 4:
        # Broaden — pull recent high-confidence memories if search returns little
        recent = mrepo.recent(owner_user_id, hours=168, limit=12)
        seen = {m.id for m in memories}
        for m in recent:
            if m.id not in seen:
                memories.append(m)
            if len(memories) >= limit:
                break

    risks       = mrepo.active_risks(owner_user_id)[:5]
    goals       = mrepo.goals(owner_user_id)[:5]
    constraints = ConstraintRepository(db).all_active(owner_user_id)[:8]
    divergences = DivergenceRepository(db).unresolved(owner_user_id, limit=5)

    parts: List[str] = []

    if memories:
        parts.append("RELEVANT MEMORIES:")
        for m in memories:
            parts.append(
                f"  [{m.memory_type}|{m.product_source}|conf:{m.confidence:.0%}] {m.content}"
            )

    if risks:
        parts.append("\nACTIVE RISKS:")
        for r in risks:
            parts.append(f"  {r.content}")

    if goals:
        parts.append("\nACTIVE GOALS:")
        for g in goals:
            parts.append(f"  {g.content}")

    if constraints:
        parts.append("\nACTIVE CONSTRAINTS:")
        for c in constraints:
            hard_tag = "HARD" if c.is_hard_constraint else "soft"
            parts.append(f"  [{hard_tag}|{c.constraint_type}] {c.content}")

    if divergences:
        parts.append("\nUNRESOLVED DIVERGENCES:")
        for d in divergences:
            parts.append(f"  [{d.divergence_type}] {d.description[:100]}")

    return "\n".join(parts) if parts else "No relevant memories or data found for this query."


# ── Session history ───────────────────────────────────────────────────────────────

def _recent_history(session, turns: int = 6) -> List[Dict[str, str]]:
    """Return the last N turns from the session transcript as LLM history."""
    transcript = session.transcript or []
    recent = transcript[-(turns * 2):]  # each turn is 2 messages (user + assistant)
    return [{"role": t["role"], "content": t["content"]} for t in recent]


# ── Main entry point ──────────────────────────────────────────────────────────────

async def chat(
    db: DBSession,
    owner_user_id: int,
    message: str,
    *,
    context_name: Optional[str] = None,
    session_id: Optional[str] = None,
    page: Optional[str] = None,
    product: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Process one message. Returns a dict with the response, mode, and session_id.

    Session management:
    - If session_id provided, continue that session (regardless of context).
    - Otherwise, open or continue the active session for this context.
    - If context_name is None, default to "PHANG" (global).
    """
    from ..repositories import ContextRepository

    # Resolve context
    context_id: Optional[str] = None
    if context_name:
        ctx = ContextRepository(db).get_or_create(owner_user_id, context_name)
        context_id = ctx.id

    # Resolve session
    sess_repo = SessionRepository(db)
    if session_id:
        session = sess_repo.get(session_id)
        if not session or session.owner_user_id != owner_user_id:
            session = sess_repo.get_or_create_open(owner_user_id, context_id)
    else:
        session = sess_repo.get_or_create_open(owner_user_id, context_id)

    # Route to mode
    mode = _route(message)

    # Build context text
    if mode == "live":
        system = _LIVE_SYSTEM
        context_text = _build_live_context(db, owner_user_id)
    else:
        system = _INTEL_SYSTEM
        context_text = _build_intel_context(db, owner_user_id, message)

    # Add page/product context hint
    origin_hint = ""
    if page or product:
        origin_hint = f"\n\nUser is currently on: {product or ''}/{page or ''}."

    # Build history from session transcript (last 6 turns)
    history = _recent_history(session, turns=6)

    # Compose user message for LLM
    user_content = (
        f"Context data:\n{context_text}{origin_hint}\n\n"
        f"---\nQuestion: {message}"
    )

    # Call LLM
    response = await llm.complete(
        system=system,
        user=user_content,
        history=history,
        max_tokens=600,
        temperature=0.4,
    )

    if not response:
        response = _fallback_response(mode, context_text)

    # Persist turn to session transcript
    sess_repo.append_message(session, "user", message)
    sess_repo.append_message(session, "assistant", response)

    log.info("chat (%s) user=%d session=%s → %d chars",
             mode, owner_user_id, session.id, len(response))

    return {
        "response":   response,
        "mode":       mode,
        "session_id": session.id,
        "context_id": session.context_id,
    }


def _fallback_response(mode: str, context_text: str) -> str:
    """Returns when DeepSeek is unavailable — never crashes."""
    if mode == "live":
        if "available" in context_text.lower() and "false" not in context_text.lower():
            return (
                "Product data is available but I cannot generate a response right now "
                "(language service unavailable). Check the data directly via the dashboard."
            )
    return (
        "I cannot generate a response right now — the language service is unavailable. "
        "The underlying data (memories, decisions, divergences) is intact and queryable."
    )
