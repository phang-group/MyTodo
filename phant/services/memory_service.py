"""
phant/services/memory_service.py — belief creation.

This is the ONLY writer of memories in the system. Products emit events; PHANT
creates memories. No product code path may insert into phant_memories — it must
go through here (or through ingest_service, which calls here).

On creation we attempt a best-effort embedding so the pgvector column is
populated from day one. Vector SEARCH is deferred, but vector STORAGE is not —
that is the cheap insurance that avoids a future re-embedding migration.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from database import engine
from ..models import PhantMemory
from ..repositories import ContextRepository, MemoryRepository
from .. import llm

log = logging.getLogger("phant.memory")

# Default product → context-name mapping. A memory always lands in a namespace.
PRODUCT_CONTEXT = {
    "mytodo":   "MyTodo",
    "infopro":  "InfoPro",
    "nextdoor": "NextDoor",
    "bff":      "BFF",
    "z3":       "Z3",
    "phant":    "PHANG",
    "manual":   "PHANG",
}

VALID_TYPES = {
    "fact", "belief", "observation", "goal", "commitment",
    "pattern", "risk", "opportunity", "preference", "identity",
}


def resolve_context_id(db: Session, owner_user_id: int,
                       context_name: Optional[str], product: str) -> str:
    name = context_name or PRODUCT_CONTEXT.get(product, "PHANG")
    ctx = ContextRepository(db).get_or_create(owner_user_id, name)
    return ctx.id


async def create_memory(
    db: Session,
    *,
    owner_user_id: int,
    content: str,
    memory_type: str = "observation",
    product_source: str = "phant",
    context_name: Optional[str] = None,
    confidence: float = 0.7,
    is_verified: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
    source_event_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> PhantMemory:
    if memory_type not in VALID_TYPES:
        memory_type = "observation"

    context_id = resolve_context_id(db, owner_user_id, context_name, product_source)

    mem = MemoryRepository(db).create(
        owner_user_id=owner_user_id,
        context_id=context_id,
        session_id=session_id,
        product_source=product_source,
        memory_type=memory_type,
        content=content.strip(),
        confidence=max(0.0, min(1.0, confidence)),
        is_verified=is_verified,
        meta=metadata or {},
        source_event_id=source_event_id,
    )

    await _attach_embedding(db, mem)
    return mem


async def _attach_embedding(db: Session, mem: PhantMemory) -> None:
    """Best-effort. Never raises into the request path."""
    if engine.dialect.name != "postgresql":
        return
    vector = await llm.embed(mem.content)
    if not vector:
        return
    try:
        literal = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
        db.execute(
            text("UPDATE phant_memories SET embedding = CAST(:v AS vector), "
                 "embedding_model = :m WHERE id = :id"),
            {"v": literal, "m": llm.EMBEDDING_MODEL, "id": mem.id},
        )
        db.commit()
    except Exception as e:  # noqa: BLE001 — column/extension may be absent in V1
        db.rollback()
        log.debug("embedding store skipped for %s: %s", mem.id, e)


def list_memories(db: Session, owner_user_id: int, **filters) -> List[PhantMemory]:
    return MemoryRepository(db).query(owner_user_id, **filters)
