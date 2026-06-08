"""phant/repositories/contexts.py — memory-namespace access."""

from __future__ import annotations

from typing import List, Optional

from ..models import PhantContext
from .base import BaseRepository


class ContextRepository(BaseRepository[PhantContext]):
    model = PhantContext

    def get_by_name(self, owner_user_id: int, name: str) -> Optional[PhantContext]:
        return (
            self.db.query(PhantContext)
            .filter(PhantContext.owner_user_id == owner_user_id,
                    PhantContext.name == name)
            .first()
        )

    def get_or_create(self, owner_user_id: int, name: str,
                      description: str = "") -> PhantContext:
        """Idempotent: contexts emerge as products/areas are first observed."""
        existing = self.get_by_name(owner_user_id, name)
        if existing:
            return existing
        ctx = PhantContext(
            owner_user_id=owner_user_id,
            name=name,
            description=description,
        )
        return self.add(ctx)

    def list(self, owner_user_id: int, active_only: bool = True) -> List[PhantContext]:
        q = self.db.query(PhantContext).filter(PhantContext.owner_user_id == owner_user_id)
        if active_only:
            q = q.filter(PhantContext.is_active.is_(True))
        return q.order_by(PhantContext.created_at.asc()).all()
