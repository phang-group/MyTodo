"""phant/repositories/sessions.py — conversational-thread access."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..models import PhantSession
from .base import BaseRepository


class SessionRepository(BaseRepository[PhantSession]):
    model = PhantSession

    def get_open(self, owner_user_id: int,
                 context_id: Optional[str]) -> Optional[PhantSession]:
        return (
            self.db.query(PhantSession)
            .filter(PhantSession.owner_user_id == owner_user_id,
                    PhantSession.context_id == context_id,
                    PhantSession.closed_at.is_(None))
            .order_by(PhantSession.last_active_at.desc())
            .first()
        )

    def get_or_create_open(self, owner_user_id: int,
                           context_id: Optional[str]) -> PhantSession:
        existing = self.get_open(owner_user_id, context_id)
        if existing:
            return existing
        sess = PhantSession(
            owner_user_id=owner_user_id,
            context_id=context_id,
            transcript=[],
        )
        return self.add(sess)

    def append_message(self, session: PhantSession, role: str, content: str) -> PhantSession:
        """Append a turn to the thread. JSON column is reassigned to mark it dirty."""
        transcript = list(session.transcript or [])
        transcript.append({
            "role": role,
            "content": content,
            "ts": datetime.utcnow().isoformat(),
        })
        session.transcript = transcript
        session.last_active_at = datetime.utcnow()
        return self.save(session)

    def list(self, owner_user_id: int, limit: int = 30) -> List[PhantSession]:
        return (
            self.db.query(PhantSession)
            .filter(PhantSession.owner_user_id == owner_user_id)
            .order_by(PhantSession.last_active_at.desc())
            .limit(limit)
            .all()
        )

    def close(self, session: PhantSession, summary: str = "") -> PhantSession:
        session.closed_at = datetime.utcnow()
        if summary:
            session.summary = summary
        return self.save(session)
