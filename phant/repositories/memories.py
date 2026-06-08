"""phant/repositories/memories.py — the belief-corpus access layer."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import or_

from ..models import PhantMemory
from .base import BaseRepository


class MemoryRepository(BaseRepository[PhantMemory]):
    model = PhantMemory

    # ── Write ────────────────────────────────────────────────────────────────
    def create(self, **fields) -> PhantMemory:
        mem = PhantMemory(**fields)
        if mem.confidence is not None and not mem.confidence_history:
            mem.confidence_history = [{
                "value": mem.confidence,
                "changed_at": datetime.utcnow().isoformat(),
                "reason": "created",
            }]
        return self.add(mem)

    def update_confidence(self, mem: PhantMemory, value: float, reason: str) -> PhantMemory:
        history = list(mem.confidence_history or [])
        history.append({
            "value": value,
            "changed_at": datetime.utcnow().isoformat(),
            "reason": reason or "manual_update",
        })
        mem.confidence_history = history
        mem.confidence = value
        mem.last_confirmed_at = datetime.utcnow()
        return self.save(mem)

    def archive(self, mem: PhantMemory) -> PhantMemory:
        mem.status = "archived"
        mem.archived_at = datetime.utcnow()
        return self.save(mem)

    def supersede(self, old: PhantMemory, new_id: str) -> PhantMemory:
        old.status = "superseded"
        old.superseded_by = new_id
        old.archived_at = datetime.utcnow()
        return self.save(old)

    # ── Read ─────────────────────────────────────────────────────────────────
    def query(
        self,
        owner_user_id: int,
        *,
        context_id: Optional[str] = None,
        types: Optional[List[str]] = None,
        product: Optional[str] = None,
        status: Optional[str] = "active",
        search: Optional[str] = None,
        limit: int = 20,
    ) -> List[PhantMemory]:
        q = self.db.query(PhantMemory).filter(PhantMemory.owner_user_id == owner_user_id)
        if status:
            q = q.filter(PhantMemory.status == status)
        if context_id:
            q = q.filter(PhantMemory.context_id == context_id)
        if types:
            q = q.filter(PhantMemory.memory_type.in_(types))
        if product:
            q = q.filter(PhantMemory.product_source == product)
        if search:
            like = f"%{search}%"
            q = q.filter(PhantMemory.content.ilike(like))
        return q.order_by(PhantMemory.created_at.desc()).limit(limit).all()

    def recent(self, owner_user_id: int, hours: int = 24, limit: int = 40) -> List[PhantMemory]:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return (
            self.db.query(PhantMemory)
            .filter(PhantMemory.owner_user_id == owner_user_id,
                    PhantMemory.status == "active",
                    PhantMemory.created_at >= cutoff)
            .order_by(PhantMemory.created_at.desc())
            .limit(limit)
            .all()
        )

    def by_type(self, owner_user_id: int, memory_type: str, limit: int = 50) -> List[PhantMemory]:
        return (
            self.db.query(PhantMemory)
            .filter(PhantMemory.owner_user_id == owner_user_id,
                    PhantMemory.status == "active",
                    PhantMemory.memory_type == memory_type)
            .order_by(PhantMemory.confidence.desc(), PhantMemory.created_at.desc())
            .limit(limit)
            .all()
        )

    def active_risks(self, owner_user_id: int) -> List[PhantMemory]:
        return self.by_type(owner_user_id, "risk")

    def goals(self, owner_user_id: int) -> List[PhantMemory]:
        return self.by_type(owner_user_id, "goal")

    def commitments(self, owner_user_id: int) -> List[PhantMemory]:
        return self.by_type(owner_user_id, "commitment")

    def unembedded(self, limit: int = 50) -> List[PhantMemory]:
        """Active memories with no embedding yet (for the embed job)."""
        # embedding column is added by migrations; query defensively via raw filter
        return (
            self.db.query(PhantMemory)
            .filter(PhantMemory.status == "active")
            .order_by(PhantMemory.created_at.desc())
            .limit(limit)
            .all()
        )

    def stale(self, owner_user_id: Optional[int], days: int) -> List[PhantMemory]:
        """Active memories not confirmed within `days` (for the decay job)."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        q = self.db.query(PhantMemory).filter(
            PhantMemory.status == "active",
            PhantMemory.last_confirmed_at < cutoff,
        )
        if owner_user_id is not None:
            q = q.filter(PhantMemory.owner_user_id == owner_user_id)
        return q.all()

    def counts_by_context(self, owner_user_id: int, context_id: str) -> int:
        return (
            self.db.query(PhantMemory)
            .filter(PhantMemory.owner_user_id == owner_user_id,
                    PhantMemory.context_id == context_id,
                    PhantMemory.status == "active")
            .count()
        )
