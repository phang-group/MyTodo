"""phant/repositories/decisions.py — decision-record access (the FID)."""

from __future__ import annotations

from typing import List, Optional

from ..models import PhantDecision, PhantOutcome
from .base import BaseRepository


class DecisionRepository(BaseRepository[PhantDecision]):
    model = PhantDecision

    def create(self, **fields) -> PhantDecision:
        return self.add(PhantDecision(**fields))

    def list(
        self,
        owner_user_id: int,
        *,
        context_id: Optional[str] = None,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[PhantDecision]:
        q = self.db.query(PhantDecision).filter(PhantDecision.owner_user_id == owner_user_id)
        if context_id:
            q = q.filter(PhantDecision.context_id == context_id)
        if domain:
            q = q.filter(PhantDecision.domain == domain)
        if status:
            q = q.filter(PhantDecision.status == status)
        return q.order_by(PhantDecision.created_at.desc()).limit(limit).all()

    def orphaned(self, owner_user_id: int, older_than=None) -> List[PhantDecision]:
        """
        Confirmed decisions with no recorded outcome — the raw input to the
        decision_orphaned divergence. `older_than` (datetime) optionally restricts
        to decisions decided before a cutoff.
        """
        outcome_decision_ids = self.db.query(PhantOutcome.decision_id).subquery()
        q = (
            self.db.query(PhantDecision)
            .filter(PhantDecision.owner_user_id == owner_user_id,
                    PhantDecision.status == "confirmed",
                    PhantDecision.id.notin_(outcome_decision_ids))
        )
        if older_than is not None:
            q = q.filter(PhantDecision.decided_at.isnot(None),
                         PhantDecision.decided_at < older_than)
        return q.order_by(PhantDecision.decided_at.asc()).all()

    def with_outcome_status(self, owner_user_id: int, limit: int = 50):
        """Return [(decision, outcome_or_None)] for the Intelligence view."""
        decisions = self.list(owner_user_id, limit=limit)
        out: list = []
        for d in decisions:
            outcome = (
                self.db.query(PhantOutcome)
                .filter(PhantOutcome.decision_id == d.id)
                .order_by(PhantOutcome.created_at.desc())
                .first()
            )
            out.append((d, outcome))
        return out

    def mark_decided(self, decision: PhantDecision) -> PhantDecision:
        from datetime import datetime
        if decision.decided_at is None:
            decision.decided_at = datetime.utcnow()
        return self.save(decision)
