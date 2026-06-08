"""
phant/services/brief_service.py — the daily intelligence brief.

The brief is PHANT's primary synthesis output. It reads across every PHANT
layer — recent memories, ecosystem state, active risks, open decisions with no
outcome, unresolved divergences, and hard constraints — and produces a structured
intelligence report. The LLM renders the narrative; the data below it is the
ground truth.

V1 format:
    • Ecosystem pulse (live MyTodo state)
    • Active risks and high-priority concerns
    • Open decisions with no outcomes recorded
    • Unresolved divergences (the challenges)
    • 3 PHANT observations from recent intelligence
    • Single top recommendation

The brief is logged as a ChatMessage for rendering in the existing UI.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from sqlalchemy.orm import Session

from ..repositories import (
    ConstraintRepository,
    DecisionRepository,
    DivergenceRepository,
    MemoryRepository,
)
from ..services.ecosystem_service import snapshot, snapshot_text
from ..services.decision_service import calibration_summary
from .. import llm

log = logging.getLogger("phant.brief")

_BRIEF_SYSTEM = """\
You are PHANT — the intelligence layer above the PHANG ecosystem. You are not a
chatbot. You are an intelligence system that helps the founder (Boluwatife Faturoti,
solo operator, AI-native infrastructure company, Lagos) make better decisions by
synthesising reality from across his products and memory.

The daily brief is a concise, high-signal intelligence report. Deliver it in this
exact structure:

**ECOSYSTEM PULSE**
One paragraph on the state of active products based on the data below.

**ACTIVE RISKS** (numbered list, worst first)
Only risks that require attention or decision. Omit if there are none.

**OPEN DECISIONS**
Decisions confirmed but with no outcome recorded — accountability gaps. Omit if none.

**DIVERGENCES**
Detected gaps between what was said and what happened. Be direct. Omit if none.

**INTELLIGENCE**
3 observations drawn from recent memories. Patterns, connections, or implications
the founder may not have noticed. Not summaries — synthesis.

**RECOMMENDATION**
One specific, actionable recommendation for today. Not generic advice. Ground it
in the data. One sentence.

Rules:
- No emoji. No filler phrases ("Certainly!", "Great question!"). No bullet padding.
- Use metric numbers where available.
- Where data is absent (marked "unavailable"), say so briefly and move on.
- Tone: direct, enterprise-grade, no cheerleading.
- Total length: 350–500 words.
"""


async def generate_daily_brief(
    db: Session,
    owner_user_id: int,
    is_founder: bool = True,
) -> Dict[str, Any]:
    """
    Generate the daily intelligence brief. Returns a structured dict with both
    the rendered text (for the UI) and the raw data (for downstream inspection).
    """
    # ── 1. Gather all inputs in parallel ────────────────────────────────────
    ecosystem_snap = snapshot(db, owner_user_id, is_founder)
    eco_text = snapshot_text(ecosystem_snap)

    recent = MemoryRepository(db).recent(owner_user_id, hours=48, limit=30)
    risks  = MemoryRepository(db).active_risks(owner_user_id)
    goals  = MemoryRepository(db).goals(owner_user_id)
    commitments = MemoryRepository(db).commitments(owner_user_id)

    open_decisions = DecisionRepository(db).list(
        owner_user_id, status="confirmed", limit=20
    )
    # Narrow to those with no outcome
    outcome_orphans = DecisionRepository(db).orphaned(owner_user_id)

    divergences = DivergenceRepository(db).unresolved(owner_user_id, limit=10)
    constraints = ConstraintRepository(db).all_active(owner_user_id)
    calibration = calibration_summary(db, owner_user_id)

    # ── 2. Build LLM prompt context ──────────────────────────────────────────
    context_parts = [
        f"DATE: {datetime.utcnow().strftime('%Y-%m-%d')}",
        "",
        eco_text,
    ]

    if risks:
        context_parts.append("\nACTIVE RISKS:")
        for r in risks[:8]:
            context_parts.append(f"  [{r.confidence:.0%} confidence] {r.content}")

    if goals:
        context_parts.append("\nACTIVE GOALS:")
        for g in goals[:5]:
            m = g.meta or {}
            deadline = m.get("deadline", "no deadline")
            context_parts.append(f"  {g.content} (deadline: {deadline})")

    if commitments:
        context_parts.append("\nACTIVE COMMITMENTS:")
        for c in commitments[:5]:
            context_parts.append(f"  {c.content}")

    if outcome_orphans:
        context_parts.append(f"\nOPEN DECISIONS (no outcome recorded): {len(outcome_orphans)}")
        for d in outcome_orphans[:5]:
            ago = ""
            if d.decided_at:
                days = (datetime.utcnow() - d.decided_at).days
                ago = f" — {days}d ago"
            context_parts.append(f"  [{d.domain}] {d.title}{ago}")

    if divergences:
        context_parts.append(f"\nUNRESOLVED DIVERGENCES: {len(divergences)}")
        for dv in divergences[:5]:
            context_parts.append(
                f"  [{dv.divergence_type}] (severity {dv.severity:.1f}) {dv.description[:120]}"
            )

    if recent:
        context_parts.append(f"\nRECENT MEMORIES (last 48h): {len(recent)}")
        for m in recent[:12]:
            context_parts.append(f"  [{m.memory_type}|{m.product_source}] {m.content[:120]}")

    hard_constraints = [c for c in constraints if c.is_hard_constraint]
    if hard_constraints:
        context_parts.append("\nHARD CONSTRAINTS (govern all recommendations):")
        for c in hard_constraints[:5]:
            context_parts.append(f"  {c.content}")

    if calibration.get("sample_size", 0) > 3:
        context_parts.append(
            f"\nPHANT CALIBRATION: mean_delta={calibration['mean_delta']}, "
            f"signal={calibration['accuracy_signal']}, n={calibration['sample_size']}"
        )

    context_text = "\n".join(context_parts)

    # ── 3. Call LLM ──────────────────────────────────────────────────────────
    brief_text = await llm.complete(
        system=_BRIEF_SYSTEM,
        user=f"Generate today's intelligence brief based on the following data:\n\n{context_text}",
        max_tokens=700,
        temperature=0.3,
    )

    if not brief_text:
        brief_text = _fallback_brief(ecosystem_snap, risks, outcome_orphans, divergences)

    # ── 4. Return structured result ──────────────────────────────────────────
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "brief": brief_text,
        "stats": {
            "recent_memories":   len(recent),
            "active_risks":      len(risks),
            "open_decisions":    len(outcome_orphans),
            "divergences":       len(divergences),
            "hard_constraints":  len(hard_constraints),
            "calibration":       calibration,
        },
        "ecosystem": ecosystem_snap,
    }


def _fallback_brief(ecosystem_snap, risks, orphans, divergences) -> str:
    """LLM-free brief when DeepSeek is unavailable. Never crashes."""
    mt = ecosystem_snap.get("mytodo", {})
    lines = ["**ECOSYSTEM PULSE**"]
    if mt.get("available"):
        lines.append(
            f"MyTodo: {mt['active_initiatives']} initiatives, "
            f"{mt['open_tasks']} open tasks ({mt['overdue_tasks']} overdue), "
            f"NGN {mt.get('revenue_last_7d', 0):,.0f} revenue last 7 days."
        )
    else:
        lines.append("MyTodo snapshot unavailable.")

    if risks:
        lines.append("\n**ACTIVE RISKS**")
        for r in risks[:3]:
            lines.append(f"1. {r.content}")

    if orphans:
        lines.append(f"\n**OPEN DECISIONS**\n{len(orphans)} decisions with no outcome recorded.")

    if divergences:
        lines.append(f"\n**DIVERGENCES**\n{len(divergences)} unresolved divergences.")

    lines.append("\n**RECOMMENDATION**\nReview open decisions and record outcomes to close the calibration loop.")
    return "\n".join(lines)
