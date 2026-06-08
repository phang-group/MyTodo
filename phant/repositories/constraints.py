"""phant/repositories/constraints.py — reasoning-rule access."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import or_

from ..models import PhantConstraint
from .base import BaseRepository


class ConstraintRepository(BaseRepository[PhantConstraint]):
    model = PhantConstraint

    def create(self, **fields) -> PhantConstraint:
        return self.add(PhantConstraint(**fields))

    def active(self, owner_user_id: int,
               context_id: Optional[str] = None) -> List[PhantConstraint]:
        """
        Active constraints that apply in scope: always global constraints
        (context_id IS NULL) plus any scoped to the given context. These are
        injected into every recommendation — never left to similarity search.
        """
        q = self.db.query(PhantConstraint).filter(
            PhantConstraint.owner_user_id == owner_user_id,
            PhantConstraint.is_active.is_(True),
        )
        if context_id:
            q = q.filter(or_(PhantConstraint.context_id.is_(None),
                             PhantConstraint.context_id == context_id))
        else:
            q = q.filter(PhantConstraint.context_id.is_(None))
        return q.order_by(PhantConstraint.is_hard_constraint.desc(),
                          PhantConstraint.created_at.desc()).all()

    def all_active(self, owner_user_id: int) -> List[PhantConstraint]:
        return (
            self.db.query(PhantConstraint)
            .filter(PhantConstraint.owner_user_id == owner_user_id,
                    PhantConstraint.is_active.is_(True))
            .order_by(PhantConstraint.is_hard_constraint.desc(),
                      PhantConstraint.created_at.desc())
            .all()
        )

    def deactivate(self, constraint: PhantConstraint, reason: str) -> PhantConstraint:
        constraint.is_active = False
        constraint.deactivation_reason = reason
        return self.save(constraint)
