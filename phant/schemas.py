"""
phant/schemas.py — request validation models (Pydantic v2).

Responses are serialised via each model's .to_dict() and returned as plain
dicts / JSONResponse, which keeps full control over the wire shape (and avoids
ORM-serialisation friction around the `metadata` column alias). These schemas
therefore cover INPUT only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Events (product → PHANT) ─────────────────────────────────────────────────────

class EventIn(BaseModel):
    """A fact emitted by a product. PHANT decides whether it becomes a memory."""
    product:     str
    event_type:  str
    title:       str
    description: str = ""
    severity:    str = "info"                      # info|warning|critical
    occurred_at: Optional[datetime] = None
    metadata:    Dict[str, Any] = Field(default_factory=dict)


# ── Memories ─────────────────────────────────────────────────────────────────────

class MemoryIn(BaseModel):
    content:        str
    memory_type:    str = "observation"
    product_source: str = "phant"
    context:        Optional[str] = None           # context name; resolved/created on write
    confidence:     float = 0.7
    is_verified:    bool = True
    metadata:       Dict[str, Any] = Field(default_factory=dict)
    source_event_id: Optional[str] = None


class ConfidenceUpdate(BaseModel):
    confidence: float
    reason:     str = ""


# ── Decisions ────────────────────────────────────────────────────────────────────

class DecisionOptionIn(BaseModel):
    option:             str
    rationale_for:      str = ""
    rationale_against:  str = ""


class DecisionIn(BaseModel):
    title:                str
    situation:            str
    chosen_option:        str
    domain:               str = "general"
    context:              Optional[str] = None
    options_considered:   List[DecisionOptionIn] = Field(default_factory=list)
    reasoning:            str = ""
    phant_recommended:    Optional[bool] = None
    phant_recommendation: Optional[str] = None
    founder_agreed:       Optional[bool] = None
    confidence_at_decision: Optional[float] = None
    product_source:       Optional[str] = None
    status:               str = "confirmed"        # decisions are usually recorded after the fact


# ── Outcomes ─────────────────────────────────────────────────────────────────────

class OutcomeIn(BaseModel):
    decision_id:         str
    outcome_description: str
    outcome_type:        str = "partial"           # success|failure|partial|unexpected
    metric_expected:     Dict[str, Any] = Field(default_factory=dict)
    metric_actual:       Dict[str, Any] = Field(default_factory=dict)
    retrospective_insight: str = ""
    observed_at:         Optional[datetime] = None


# ── Constraints ──────────────────────────────────────────────────────────────────

class ConstraintIn(BaseModel):
    content:            str
    constraint_type:    str = "prohibit"           # prohibit|require|prefer|avoid
    is_hard_constraint: bool = True
    context:            Optional[str] = None        # null/None = global


class ConstraintDeactivate(BaseModel):
    deactivation_reason: str = ""


# ── Divergences ──────────────────────────────────────────────────────────────────

class DivergenceResolve(BaseModel):
    status:          str = "resolved"              # acknowledged|resolved|dismissed
    resolution_note: str = ""


# ── Chat ─────────────────────────────────────────────────────────────────────────

class ChatIn(BaseModel):
    message:    str
    context:    Optional[str] = None               # optional context name
    session_id: Optional[str] = None               # continue an existing thread
    page:       Optional[str] = None               # product/page the user asked from
    product:    Optional[str] = None
