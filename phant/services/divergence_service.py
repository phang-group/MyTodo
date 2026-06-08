"""
phant/services/divergence_service.py — the challenge engine.

This is the mechanism that makes PHANT something other than a journal. A journal
records what you said. PHANT detects where reality diverged from what you said —
and surfaces the gap as a challenge.

Five detection passes, each idempotent (safe to run repeatedly via cron or on request):

    commitment_missed     — a commitment whose deadline is past and status is still active
    decision_orphaned     — a confirmed decision older than 90 days with no outcome
    belief_contradiction  — two active, high-confidence memories with opposing content
    goal_drift            — a goal approaching its deadline with no recent confirmation
    constraint_violation  — a decision whose chosen_option may conflict with a hard rule

DivergenceRepository.upsert() ensures idempotency — repeated detection runs update
the description/severity but never duplicate the row.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List

from sqlalchemy.orm import Session

from ..repositories import (
    ConstraintRepository,
    DecisionRepository,
    DivergenceRepository,
    MemoryRepository,
)
from ..models import PhantDivergence

log = logging.getLogger("phant.divergence")


async def detect_all(db: Session, owner_user_id: int) -> List[PhantDivergence]:
    """
    Run all five detection passes and return the list of active divergences for
    this owner after detection. Safe to call repeatedly — each pass is idempotent.
    """
    _detect_commitment_missed(db, owner_user_id)
    _detect_decision_orphaned(db, owner_user_id)
    _detect_goal_drift(db, owner_user_id)
    _detect_constraint_violation(db, owner_user_id)
    # belief_contradiction is more expensive; run last
    _detect_belief_contradiction(db, owner_user_id)

    all_unresolved = DivergenceRepository(db).unresolved(owner_user_id, limit=100)
    log.info("divergence scan complete for user %d: %d unresolved", owner_user_id, len(all_unresolved))
    return all_unresolved


# ── Detection passes ─────────────────────────────────────────────────────────────

def _detect_commitment_missed(db: Session, owner_user_id: int) -> None:
    """
    A commitment memory whose metadata.deadline is in the past and whose
    metadata.status is not 'fulfilled' or 'cancelled'.
    """
    repo = DivergenceRepository(db)
    commitments = MemoryRepository(db).commitments(owner_user_id)
    now = datetime.utcnow()

    for mem in commitments:
        meta = mem.meta or {}
        deadline_str = meta.get("deadline")
        if not deadline_str:
            continue

        try:
            deadline = datetime.fromisoformat(str(deadline_str))
        except (ValueError, TypeError):
            continue

        if deadline >= now:
            continue  # not yet missed

        commitment_status = str(meta.get("status", "active")).lower()
        if commitment_status in ("fulfilled", "cancelled", "closed"):
            continue

        days_late = (now - deadline).days
        severity = min(1.0, 0.5 + (days_late / 30) * 0.3)

        repo.upsert(
            owner_user_id=owner_user_id,
            divergence_type="commitment_missed",
            description=(
                f"Commitment overdue by {days_late}d: \"{mem.content[:100]}\" "
                f"(deadline: {deadline.date()}, status: {commitment_status})"
            ),
            severity=round(severity, 2),
            context_id=mem.context_id,
            entity_a_type="memory",
            entity_a_id=mem.id,
        )


def _detect_decision_orphaned(db: Session, owner_user_id: int) -> None:
    """
    A confirmed decision older than 90 days with no outcome recorded.
    Severity increases with age — a 6-month-old orphaned decision is a bigger
    accountability gap than a 3-month-old one.
    """
    cutoff = datetime.utcnow() - timedelta(days=90)
    repo = DivergenceRepository(db)
    orphans = DecisionRepository(db).orphaned(owner_user_id, older_than=cutoff)

    for decision in orphans:
        days_old = (datetime.utcnow() - (decision.decided_at or decision.created_at)).days
        severity = min(0.9, 0.4 + (days_old / 180) * 0.4)

        repo.upsert(
            owner_user_id=owner_user_id,
            divergence_type="decision_orphaned",
            description=(
                f"Decision \"{decision.title[:80]}\" confirmed {days_old}d ago "
                f"with no outcome recorded. The calibration loop is open."
            ),
            severity=round(severity, 2),
            context_id=decision.context_id,
            entity_a_type="decision",
            entity_a_id=decision.id,
        )


def _detect_goal_drift(db: Session, owner_user_id: int) -> None:
    """
    A goal approaching its deadline (within 14 days) that has not been confirmed
    recently (last_confirmed_at > 30 days ago). This is the "silent failure" pattern —
    goals drift without explicit abandonment or pivot.
    """
    repo = DivergenceRepository(db)
    goals = MemoryRepository(db).goals(owner_user_id)
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(days=30)
    deadline_window = now + timedelta(days=14)

    for goal in goals:
        meta = goal.meta or {}
        deadline_str = meta.get("deadline")
        if not deadline_str:
            continue

        try:
            deadline = datetime.fromisoformat(str(deadline_str))
        except (ValueError, TypeError):
            continue

        # Only flag goals approaching deadline, not ones far away
        if deadline > deadline_window or deadline < now - timedelta(days=1):
            continue

        last_confirmed = goal.last_confirmed_at
        if last_confirmed and last_confirmed >= stale_cutoff:
            continue  # recently confirmed — no drift

        days_to_deadline = max(0, (deadline - now).days)
        severity = 0.6 + (0.3 * (1 - days_to_deadline / 14))

        repo.upsert(
            owner_user_id=owner_user_id,
            divergence_type="goal_drift",
            description=(
                f"Goal approaches deadline in {days_to_deadline}d with no recent update: "
                f"\"{goal.content[:100]}\". Last confirmed: "
                f"{last_confirmed.date() if last_confirmed else 'never'}."
            ),
            severity=round(min(0.9, severity), 2),
            context_id=goal.context_id,
            entity_a_type="memory",
            entity_a_id=goal.id,
        )


def _detect_constraint_violation(db: Session, owner_user_id: int) -> None:
    """
    A recent decision (last 14 days) whose chosen_option textually overlaps with
    an active hard constraint. This is a lightweight heuristic — not semantic
    analysis — designed to surface obvious cases for human review.

    V2 will use embedding similarity here instead of substring matching.
    """
    repo = DivergenceRepository(db)
    hard_constraints = [
        c for c in ConstraintRepository(db).all_active(owner_user_id)
        if c.is_hard_constraint
    ]
    if not hard_constraints:
        return

    cutoff = datetime.utcnow() - timedelta(days=14)
    recent_decisions = (
        db.query(__import__('phant.models', fromlist=['PhantDecision']).PhantDecision)
        .filter_by(owner_user_id=owner_user_id)
        .filter(
            __import__('phant.models', fromlist=['PhantDecision']).PhantDecision.created_at >= cutoff
        )
        .all()
    )

    for decision in recent_decisions:
        for constraint in hard_constraints:
            # Keyword overlap heuristic — look for shared significant tokens
            c_tokens = set(_significant_tokens(constraint.content))
            d_tokens = set(_significant_tokens(decision.chosen_option + " " + (decision.reasoning or "")))
            overlap = c_tokens & d_tokens
            if len(overlap) < 2:
                continue

            repo.upsert(
                owner_user_id=owner_user_id,
                divergence_type="constraint_violation",
                description=(
                    f"Decision \"{decision.title[:60]}\" may conflict with hard constraint: "
                    f"\"{constraint.content[:80]}\". Shared keywords: {', '.join(sorted(overlap)[:5])}."
                ),
                severity=0.7,
                context_id=decision.context_id,
                entity_a_type="decision",
                entity_a_id=decision.id,
                entity_b_type="constraint",
                entity_b_id=constraint.id,
            )


def _detect_belief_contradiction(db: Session, owner_user_id: int) -> None:
    """
    Two active memories with confidence >= 0.75 that appear to contradict each
    other. V1 uses a heuristic: negation keywords (not, no, never, cannot) and
    shared domain tokens. V2 will use embedding cosine distance with sign flip.

    Cap at 20 pairs per run to avoid O(n²) explosions.
    """
    repo = DivergenceRepository(db)
    high_conf = (
        db.query(__import__('phant.models', fromlist=['PhantMemory']).PhantMemory)
        .filter_by(owner_user_id=owner_user_id, status="active")
        .filter(
            __import__('phant.models', fromlist=['PhantMemory']).PhantMemory.confidence >= 0.75
        )
        .order_by(
            __import__('phant.models', fromlist=['PhantMemory']).PhantMemory.confidence.desc()
        )
        .limit(40)
        .all()
    )

    NEGATION = {"not", "no", "never", "cannot", "won't", "don't", "doesn't",
                "impossible", "avoid", "stop", "halt", "never", "refuse"}
    pairs_checked = 0

    for i, mem_a in enumerate(high_conf):
        for mem_b in high_conf[i + 1:]:
            if pairs_checked >= 20:
                return
            pairs_checked += 1

            tok_a = set(_significant_tokens(mem_a.content))
            tok_b = set(_significant_tokens(mem_b.content))
            overlap = tok_a & tok_b
            if len(overlap) < 3:
                continue

            # Check if one is a negation of the other by looking for negation near
            # shared tokens
            a_lower = mem_a.content.lower()
            b_lower = mem_b.content.lower()
            a_has_neg = any(neg in a_lower for neg in NEGATION)
            b_has_neg = any(neg in b_lower for neg in NEGATION)

            if not (a_has_neg ^ b_has_neg):  # XOR — exactly one should be negated
                continue

            repo.upsert(
                owner_user_id=owner_user_id,
                divergence_type="belief_contradiction",
                description=(
                    f"Possible contradiction between two high-confidence memories: "
                    f"\"{mem_a.content[:80]}\" vs \"{mem_b.content[:80]}\". "
                    f"Shared context: {', '.join(sorted(overlap)[:4])}."
                ),
                severity=0.6,
                context_id=mem_a.context_id,
                entity_a_type="memory",
                entity_a_id=mem_a.id,
                entity_b_type="memory",
                entity_b_id=mem_b.id,
            )


# ── Utilities ────────────────────────────────────────────────────────────────────

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "have", "has", "had", "do", "does", "did", "will",
    "would", "should", "could", "may", "might", "shall", "can", "to",
    "of", "in", "on", "at", "for", "with", "by", "from", "this", "that",
    "it", "its", "we", "our", "i", "my", "me", "he", "she", "they",
    "their", "you", "your", "all", "as", "if", "so", "not", "no",
}


def _significant_tokens(text: str) -> List[str]:
    """Extract lowercase alpha tokens longer than 3 chars, excluding stop words."""
    import re
    return [
        t for t in re.findall(r"[a-zA-Z]{4,}", text.lower())
        if t not in _STOP_WORDS
    ]
