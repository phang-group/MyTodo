"""phant/repositories/outcomes.py — outcome-record access (calibration loop)."""

from __future__ import annotations

from typing import List, Optional

from ..models import PhantOutcome
from .base import BaseRepository


class OutcomeRepository(BaseRepository[PhantOutcome]):
    model = PhantOutcome

    def create(self, **fields) -> PhantOutcome:
        return self.add(PhantOutcome(**fields))

    def for_decision(self, decision_id: str) -> List[PhantOutcome]:
        return (
            self.db.query(PhantOutcome)
            .filter(PhantOutcome.decision_id == decision_id)
            .order_by(PhantOutcome.created_at.desc())
            .all()
        )

    def latest_for_decision(self, decision_id: str) -> Optional[PhantOutcome]:
        return (
            self.db.query(PhantOutcome)
            .filter(PhantOutcome.decision_id == decision_id)
            .order_by(PhantOutcome.created_at.desc())
            .first()
        )

    def calibration_sample(self, owner_user_id: int, limit: int = 200) -> List[PhantOutcome]:
        """Outcomes with a confidence_delta — the raw calibration signal."""
        return (
            self.db.query(PhantOutcome)
            .filter(PhantOutcome.owner_user_id == owner_user_id,
                    PhantOutcome.confidence_delta.isnot(None))
            .order_by(PhantOutcome.created_at.desc())
            .limit(limit)
            .all()
        )
