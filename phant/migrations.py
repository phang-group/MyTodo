"""
phant/migrations.py — idempotent schema migrations for PHANT.

create_all() (called by database.init_db) creates the seven PHANT tables but
never alters them and cannot add a pgvector column type that SQLAlchemy's core
generic types don't model. This module fills that gap.

Every statement is idempotent and guarded — safe on every Vercel cold start,
regardless of current DB state, and a no-op (with a logged warning) if the
pgvector extension is unavailable. Nothing here can break startup.

The embedding column is added from day one so that activating vector search in a
later phase requires zero migration: the column is simply already there,
populated best-effort by phant.llm.embed().
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from database import engine

log = logging.getLogger("phant.migrations")

# (statement, description). Each runs in its own transaction so one failure never
# blocks the rest.
_PG_STATEMENTS = [
    ("CREATE EXTENSION IF NOT EXISTS vector",
     "pgvector extension"),
    ("ALTER TABLE phant_memories ADD COLUMN IF NOT EXISTS embedding vector(1536)",
     "phant_memories.embedding"),
    # GIN index on JSON metadata accelerates risk/goal/commitment attribute queries.
    ("CREATE INDEX IF NOT EXISTS ix_phant_mem_meta ON phant_memories USING gin (metadata)",
     "phant_memories.metadata GIN index"),
]


def run() -> None:
    """Apply PHANT migrations. Postgres only — SQLite dev needs none of this."""
    dialect = engine.dialect.name
    if dialect != "postgresql":
        log.info("PHANT migrations skipped (dialect=%s, vector/GIN are Postgres-only)", dialect)
        return

    for stmt, desc in _PG_STATEMENTS:
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
            log.info("PHANT migration OK: %s", desc)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if "already exists" in msg:
                log.debug("PHANT migration skip (exists): %s", desc)
            else:
                # pgvector not installed on this instance, or insufficient privilege.
                # V1 does not query embeddings, so this is non-fatal by design.
                log.warning("PHANT migration WARNING (non-fatal): %s — %s", desc, exc)
