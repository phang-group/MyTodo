"""
phant/models.py — the PHANT cognition data model.

Seven tables. Every field is here because it captures information that becomes
expensive or impossible to reconstruct later. This is the zero-regret schema:
collect now, analyse later.

    phant_contexts      — memory namespaces (cross-product reasoning boundary)
    phant_sessions      — conversational threads (carry their own transcript)
    phant_memories      — the belief corpus (atomic claims PHANT holds true)
    phant_decisions     — first-class decision records (the Founder Intelligence Dataset)
    phant_outcomes      — what actually happened (closes the calibration loop)
    phant_constraints   — reasoning rules that govern every recommendation
    phant_divergences   — gaps between what was said and what happened (the challenge engine)

Design notes
------------
- IDs are string UUIDs generated in Python. This is cross-dialect (Postgres on
  Neon in production, SQLite in local dev) and avoids ever re-keying integer PKs.
- Structured fields use SQLAlchemy's generic JSON type (JSON on Postgres,
  TEXT-JSON on SQLite).
- `owner_user_id` scopes cognition to a workspace user (MyTodo is multi-user).
  It mirrors the products' `gateway_user_id` convention.
- The `embedding vector(1536)` column is NOT mapped here. It is added at the SQL
  level by phant/migrations.py (guarded by the pgvector extension) and written
  best-effort. It is stored-but-unused in V1 — present from day one so no future
  migration is ever needed, queried only when vector search is activated.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


# ── Context ─────────────────────────────────────────────────────────────────────

class PhantContext(Base):
    """
    A memory namespace. Answers: "for which area of the founder's operating
    reality is this relevant?" — e.g. MyTodo, InfoPro, NextDoor, PHANG, Personal.

    Context on every memory cannot be reconstructed accurately later, so it is
    captured from day one even though cross-context reasoning is deferred.
    """
    __tablename__ = "phant_contexts"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_phant_context_owner_name"),
    )

    id            = Column(String(36), primary_key=True, default=_uuid)
    owner_user_id = Column(Integer, nullable=False, index=True)
    name          = Column(String(100), nullable=False)
    description   = Column(Text, default="")          # short, human; not used computationally
    is_active     = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":         self.id,
            "name":       self.name,
            "description": self.description or "",
            "is_active":  self.is_active,
            "created_at": _iso(self.created_at),
        }


# ── Session ─────────────────────────────────────────────────────────────────────

class PhantSession(Base):
    """
    A persistent conversational thread within a context. The thread's messages
    live on the session itself (transcript), keeping the model at seven tables.

    session_id is a data-lineage field: it links memories and decisions to the
    conversation that produced them, enabling session-level analysis later.
    """
    __tablename__ = "phant_sessions"

    id            = Column(String(36), primary_key=True, default=_uuid)
    context_id    = Column(String(36), ForeignKey("phant_contexts.id"), nullable=True, index=True)
    owner_user_id = Column(Integer, nullable=False, index=True)
    summary       = Column(Text, default="")          # compressed thread intelligence (set on close)
    transcript    = Column(JSON, default=list)        # [{role, content, ts}] — append-only
    created_at    = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at     = Column(DateTime, nullable=True)

    def to_dict(self, include_transcript: bool = False) -> Dict[str, Any]:
        d = {
            "id":            self.id,
            "context_id":    self.context_id,
            "summary":       self.summary or "",
            "created_at":    _iso(self.created_at),
            "last_active_at": _iso(self.last_active_at),
            "closed_at":     _iso(self.closed_at),
            "message_count": len(self.transcript or []),
        }
        if include_transcript:
            d["transcript"] = self.transcript or []
        return d


# ── Memory ──────────────────────────────────────────────────────────────────────

class PhantMemory(Base):
    """
    The atomic unit of PHANT intelligence: a single claim PHANT believes to be
    true. Products emit events; PHANT creates memories. Products never write here.

    memory_type vocabulary (distinct reasoning objects, not labels):
        fact        — verifiable against source data
        belief      — PHANT's inference about reality (may be wrong)
        observation — unverified (is_verified = False)
        goal        — has target/deadline in metadata
        commitment  — made to a party; has status in metadata
        pattern     — higher-order synthesis across memories
        risk        — has probability/impact/review_by in metadata
        opportunity — positive valence; has window/actions in metadata
        preference  — founder preference
        identity    — durable fact about the founder/company
    """
    __tablename__ = "phant_memories"
    __table_args__ = (
        Index("ix_phant_mem_owner_status", "owner_user_id", "status"),
        Index("ix_phant_mem_context_type", "context_id", "memory_type"),
    )

    id              = Column(String(36), primary_key=True, default=_uuid)
    context_id      = Column(String(36), ForeignKey("phant_contexts.id"), nullable=True, index=True)
    session_id      = Column(String(36), ForeignKey("phant_sessions.id"), nullable=True)
    owner_user_id   = Column(Integer, nullable=False, index=True)

    product_source  = Column(String(50), nullable=False, default="phant")
    memory_type     = Column(String(50), nullable=False, default="observation")
    content         = Column(Text, nullable=False)        # 1–3 sentences; the claim

    confidence         = Column(Float, nullable=False, default=0.7)   # 0.0–1.0
    confidence_history = Column(JSON, default=list)        # [{value, changed_at, reason}] append-only
    last_confirmed_at  = Column(DateTime, default=datetime.utcnow)    # drives algorithmic decay

    status        = Column(String(20), nullable=False, default="active")  # active|archived|superseded
    is_verified   = Column(Boolean, nullable=False, default=True)         # False = observation

    superseded_by   = Column(String(36), ForeignKey("phant_memories.id"), nullable=True)  # correction chain
    contradicted_by = Column(String(36), ForeignKey("phant_memories.id"), nullable=True)  # contradiction chain

    source_event_id = Column(String(120), nullable=True)  # provenance: which event produced this
    meta            = Column("metadata", JSON, default=dict)  # goal/risk/commitment structured attrs
    embedding_model = Column(String(100), nullable=True)   # which model produced the vector (col added by migration)

    created_at  = Column(DateTime, default=datetime.utcnow)
    archived_at = Column(DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":              self.id,
            "context_id":      self.context_id,
            "session_id":      self.session_id,
            "product_source":  self.product_source,
            "memory_type":     self.memory_type,
            "content":         self.content,
            "confidence":      self.confidence,
            "confidence_history": self.confidence_history or [],
            "last_confirmed_at": _iso(self.last_confirmed_at),
            "status":          self.status,
            "is_verified":     self.is_verified,
            "superseded_by":   self.superseded_by,
            "contradicted_by": self.contradicted_by,
            "source_event_id": self.source_event_id,
            "metadata":        self.meta or {},
            "created_at":      _iso(self.created_at),
            "archived_at":     _iso(self.archived_at),
        }


# ── Decision ────────────────────────────────────────────────────────────────────

class PhantDecision(Base):
    """
    A first-class decision record — the core of the Founder Intelligence Dataset.

    A decision is NOT a memory. A memory is a belief about the world; a decision
    is a record of a reasoning act: given a situation, with alternatives A/B/C,
    the founder chose X for reasons Y, at confidence W.

    `options_considered` is the single most valuable field in the schema: rejected
    options exist only at decision time and can never be reconstructed.
    `phant_recommendation` vs `chosen_option` + `founder_agreed` is the calibration
    signal — where PHANT's judgement diverges from the founder's.
    """
    __tablename__ = "phant_decisions"
    __table_args__ = (
        Index("ix_phant_dec_owner_status", "owner_user_id", "status"),
    )

    id            = Column(String(36), primary_key=True, default=_uuid)
    context_id    = Column(String(36), ForeignKey("phant_contexts.id"), nullable=True, index=True)
    session_id    = Column(String(36), ForeignKey("phant_sessions.id"), nullable=True)
    owner_user_id = Column(Integer, nullable=False, index=True)

    product_source = Column(String(50), nullable=True)
    domain         = Column(String(50), nullable=False, default="general")  # hiring|product|distribution|finance|operations|personal|general
    title          = Column(String(300), nullable=False)
    situation      = Column(Text, nullable=False)                # the problem framing (context-state feature)
    options_considered   = Column(JSON, default=list)            # [{option, rationale_for, rationale_against}]
    chosen_option        = Column(Text, nullable=False)
    reasoning            = Column(Text, nullable=False, default="")

    phant_recommended    = Column(Boolean, nullable=True)        # did PHANT suggest this path?
    phant_recommendation = Column(Text, nullable=True)           # what PHANT actually recommended (verbatim)
    founder_agreed       = Column(Boolean, nullable=True)        # null=PHANT not consulted; True=agreed; False=overrode
    confidence_at_decision = Column(Float, nullable=True)        # founder certainty at decision time

    status      = Column(String(20), nullable=False, default="pending")  # pending|confirmed|reversed
    created_at  = Column(DateTime, default=datetime.utcnow)
    decided_at  = Column(DateTime, nullable=True)

    def to_dict(self, include_outcome: bool = False) -> Dict[str, Any]:
        d = {
            "id":             self.id,
            "context_id":     self.context_id,
            "session_id":     self.session_id,
            "product_source": self.product_source,
            "domain":         self.domain,
            "title":          self.title,
            "situation":      self.situation,
            "options_considered": self.options_considered or [],
            "chosen_option":  self.chosen_option,
            "reasoning":      self.reasoning or "",
            "phant_recommended":    self.phant_recommended,
            "phant_recommendation": self.phant_recommendation,
            "founder_agreed":       self.founder_agreed,
            "confidence_at_decision": self.confidence_at_decision,
            "status":         self.status,
            "created_at":     _iso(self.created_at),
            "decided_at":     _iso(self.decided_at),
        }
        return d


# ── Outcome ─────────────────────────────────────────────────────────────────────

class PhantOutcome(Base):
    """
    The closing record of a decision lifecycle. Without outcomes linked to
    decisions, the calibration feedback loop never exists and PHANT cannot learn
    whether its reasoning was correct. The decision→outcome pair is the training
    unit for the future founder-intelligence model.
    """
    __tablename__ = "phant_outcomes"

    id            = Column(String(36), primary_key=True, default=_uuid)
    decision_id   = Column(String(36), ForeignKey("phant_decisions.id"), nullable=False, index=True)
    owner_user_id = Column(Integer, nullable=False, index=True)

    outcome_description = Column(Text, nullable=False)
    outcome_type        = Column(String(50), nullable=False, default="partial")  # success|failure|partial|unexpected
    metric_expected     = Column(JSON, default=dict)     # what the founder expected
    metric_actual       = Column(JSON, default=dict)     # ground truth
    confidence_delta    = Column(Float, nullable=True)   # +ve = PHANT was right, -ve = PHANT was wrong
    retrospective_insight = Column(Text, default="")     # "what I learned that I didn't know at decision time"

    observed_at   = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at    = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":              self.id,
            "decision_id":     self.decision_id,
            "outcome_description": self.outcome_description,
            "outcome_type":    self.outcome_type,
            "metric_expected": self.metric_expected or {},
            "metric_actual":   self.metric_actual or {},
            "confidence_delta": self.confidence_delta,
            "retrospective_insight": self.retrospective_insight or "",
            "observed_at":     _iso(self.observed_at),
            "created_at":      _iso(self.created_at),
        }


# ── Constraint ──────────────────────────────────────────────────────────────────

class PhantConstraint(Base):
    """
    A reasoning rule, not a belief. Constraints govern what PHANT is allowed to
    recommend. They are injected into every recommendation prompt rather than
    surfaced by similarity search, which is why they are a separate table with a
    different access pattern.

    is_hard_constraint: founder-set non-negotiables (True) override all
    recommendations; PHANT-inferred preferences (False) inform but can be overridden.
    """
    __tablename__ = "phant_constraints"

    id            = Column(String(36), primary_key=True, default=_uuid)
    context_id    = Column(String(36), ForeignKey("phant_contexts.id"), nullable=True, index=True)  # null = global
    owner_user_id = Column(Integer, nullable=False, index=True)

    content            = Column(Text, nullable=False)
    constraint_type    = Column(String(50), nullable=False, default="prohibit")  # prohibit|require|prefer|avoid
    is_hard_constraint = Column(Boolean, nullable=False, default=True)
    is_active          = Column(Boolean, nullable=False, default=True)
    deactivation_reason = Column(Text, nullable=True)    # why a retired rule was retired (belief-evolution signal)

    created_at    = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":              self.id,
            "context_id":      self.context_id,
            "content":         self.content,
            "constraint_type": self.constraint_type,
            "is_hard_constraint": self.is_hard_constraint,
            "is_active":       self.is_active,
            "deactivation_reason": self.deactivation_reason,
            "created_at":      _iso(self.created_at),
        }


# ── Divergence ──────────────────────────────────────────────────────────────────

class PhantDivergence(Base):
    """
    The mechanism by which PHANT challenges rather than confirms — the single
    feature that separates an intelligence system from a journal.

    Each row is a detected gap between what was said and what happened:
        commitment_missed    — a commitment's deadline passed unresolved
        decision_orphaned    — a confirmed decision has no recorded outcome
        belief_contradiction — two active high-confidence beliefs conflict
        goal_drift           — a goal nears its deadline with no recent progress
        constraint_violation — a recent decision may have broken a hard rule
    """
    __tablename__ = "phant_divergences"
    __table_args__ = (
        Index("ix_phant_div_owner_status", "owner_user_id", "status"),
    )

    id            = Column(String(36), primary_key=True, default=_uuid)
    context_id    = Column(String(36), ForeignKey("phant_contexts.id"), nullable=True, index=True)
    owner_user_id = Column(Integer, nullable=False, index=True)

    divergence_type = Column(String(50), nullable=False)
    entity_a_type   = Column(String(50), nullable=True)   # memory|decision|constraint|goal
    entity_a_id     = Column(String(36), nullable=True)
    entity_b_type   = Column(String(50), nullable=True)
    entity_b_id     = Column(String(36), nullable=True)

    description   = Column(Text, nullable=False)
    severity      = Column(Float, nullable=False, default=0.5)   # 0.0–1.0
    status        = Column(String(20), nullable=False, default="unresolved")  # unresolved|acknowledged|resolved|dismissed

    detected_at     = Column(DateTime, default=datetime.utcnow)
    resolved_at     = Column(DateTime, nullable=True)
    resolution_note = Column(Text, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":            self.id,
            "context_id":    self.context_id,
            "divergence_type": self.divergence_type,
            "entity_a_type": self.entity_a_type,
            "entity_a_id":   self.entity_a_id,
            "entity_b_type": self.entity_b_type,
            "entity_b_id":   self.entity_b_id,
            "description":   self.description,
            "severity":      self.severity,
            "status":        self.status,
            "detected_at":   _iso(self.detected_at),
            "resolved_at":   _iso(self.resolved_at),
            "resolution_note": self.resolution_note,
        }


# All PHANT models, for explicit import in database.init_db() before create_all().
ALL_MODELS = [
    PhantContext,
    PhantSession,
    PhantMemory,
    PhantDecision,
    PhantOutcome,
    PhantConstraint,
    PhantDivergence,
]
