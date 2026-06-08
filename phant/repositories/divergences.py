"""phant/repositories/divergences.py — the challenge-engine access layer."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..models import PhantDivergence
from .base import BaseRepository


class DivergenceRepository(BaseRepository[PhantDivergence]):
    model = PhantDivergence

    def find_open(self, owner_user_id: int, divergence_type: str,
                  entity_a_id: Optional[str]) -> Optional[PhantDivergence]:
        return (
            self.db.query(PhantDivergence)
            .filter(PhantDivergence.owner_user_id == owner_user_id,
                    PhantDivergence.divergence_type == divergence_type,
                    PhantDivergence.entity_a_id == entity_a_id,
                    PhantDivergence.status == "unresolved")
            .first()
        )

    def upsert(
        self,
        owner_user_id: int,
        divergence_type: str,
        description: str,
        *,
        severity: float = 0.5,
        context_id: Optional[str] = None,
        entity_a_type: Optional[str] = None,
        entity_a_id: Optional[str] = None,
        entity_b_type: Optional[str] = None,
        entity_b_id: Optional[str] = None,
    ) -> PhantDivergence:
        """
        Create the divergence if no unresolved one already exists for this
        (type, entity_a). Idempotent — the detection job runs repeatedly and must
        not duplicate challenges.
        """
        existing = self.find_open(owner_user_id, divergence_type, entity_a_id)
        if existing:
            existing.description = description
            existing.severity = severity
            return self.save(existing)
        div = PhantDivergence(
            owner_user_id=owner_user_id,
            divergence_type=divergence_type,
            description=description,
            severity=severity,
            context_id=context_id,
            entity_a_type=entity_a_type,
            entity_a_id=entity_a_id,
            entity_b_type=entity_b_type,
            entity_b_id=entity_b_id,
        )
        return self.add(div)

    def unresolved(self, owner_user_id: int, limit: int = 50) -> List[PhantDivergence]:
        return (
            self.db.query(PhantDivergence)
            .filter(PhantDivergence.owner_user_id == owner_user_id,
                    PhantDivergence.status == "unresolved")
            .order_by(PhantDivergence.severity.desc(),
                      PhantDivergence.detected_at.desc())
            .limit(limit)
            .all()
        )

    def list(self, owner_user_id: int, status: Optional[str] = None,
             limit: int = 100) -> List[PhantDivergence]:
        q = self.db.query(PhantDivergence).filter(
            PhantDivergence.owner_user_id == owner_user_id)
        if status:
            q = q.filter(PhantDivergence.status == status)
        return q.order_by(PhantDivergence.detected_at.desc()).limit(limit).all()

    def resolve(self, div: PhantDivergence, status: str, note: str = "") -> PhantDivergence:
        div.status = status
        div.resolution_note = note
        div.resolved_at = datetime.utcnow()
        return self.save(div)
