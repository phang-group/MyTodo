"""
phant/services/decision_service.py — decision + outcome capture and calibration.

Decisions are first-class entities, not memories. A decision captures what the
founder chose, why, with what alternatives on the table, and what PHANT recommended
vs what the founder did. Outcomes close the loop: what actually happened, and by
how much did reality diverge from expectation?

The confidence_delta field on outcomes is the raw calibration signal for the future
Founder Intelligence Dataset. It is calculated here — positive means PHANT called it
right, negative means the founder overrode PHANT and was right to do so.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import PhantDecision, PhantOutcome
from ..repositories import ContextRepository, DecisionRepository, OutcomeRepository
from ..schemas import DecisionIn, OutcomeIn

log = logging.getLogger("phant.decision")


def create_decision(
    db: Session,
    owner_user_id: int,
    payload: DecisionIn,
) -> PhantDecision:
    """
    Record a decision. Usually called after the decision has been made —
    decisions are predominantly recorded in retrospect, not prospectively.
    Prospective recording (status=pending) is supported but less common.

    options_considered is the irreplaceable field: rejected options exist
    only at decision time. Always prompt for them when recording interactively.
    """
    context_id: Optional[str] = None
    if payload.context:
        ctx = ContextRepository(db).get_or_create(owner_user_id, payload.context)
        context_id = ctx.id

    options = [
        o.model_dump() if hasattr(o, "model_dump") else dict(o)
        for o in (payload.options_considered or [])
    ]

    decision = DecisionRepository(db).create(
        owner_user_id=owner_user_id,
        context_id=context_id,
        product_source=payload.product_source,
        domain=payload.domain or "general",
        title=payload.title,
        situation=payload.situation,
        options_considered=options,
        chosen_option=payload.chosen_option,
        reasoning=payload.reasoning or "",
        phant_recommended=payload.phant_recommended,
        phant_recommendation=payload.phant_recommendation,
        founder_agreed=payload.founder_agreed,
        confidence_at_decision=payload.confidence_at_decision,
        status=payload.status or "confirmed",
        decided_at=datetime.utcnow() if payload.status == "confirmed" else None,
    )
    log.info("decision recorded: %s (%s, domain=%s)", decision.id, decision.title[:60], decision.domain)
    return decision


def record_outcome(
    db: Session,
    owner_user_id: int,
    payload: OutcomeIn,
) -> PhantOutcome:
    """
    Close the calibration loop on a decision. The confidence_delta is calculated
    here from metric_expected vs metric_actual if both are provided; otherwise
    it falls back to a qualitative signal from outcome_type.

    The retrospective_insight field is the structured learning input — it captures
    what the founder learned that they didn't know at decision time. This is the
    most valuable free-text field in the schema for the FID.
    """
    decision_repo = DecisionRepository(db)
    decision = decision_repo.get(payload.decision_id)
    if not decision:
        raise ValueError(f"Decision {payload.decision_id!r} not found")
    if decision.owner_user_id != owner_user_id:
        raise PermissionError("Decision belongs to a different user")

    delta = _calculate_confidence_delta(
        decision=decision,
        outcome_type=payload.outcome_type,
        metric_expected=payload.metric_expected or {},
        metric_actual=payload.metric_actual or {},
    )

    outcome = OutcomeRepository(db).create(
        decision_id=payload.decision_id,
        owner_user_id=owner_user_id,
        outcome_description=payload.outcome_description,
        outcome_type=payload.outcome_type,
        metric_expected=payload.metric_expected or {},
        metric_actual=payload.metric_actual or {},
        confidence_delta=delta,
        retrospective_insight=payload.retrospective_insight or "",
        observed_at=payload.observed_at or datetime.utcnow(),
    )

    # Mark decision as confirmed if it was pending
    if decision.status == "pending":
        decision.status = "confirmed"
        if decision.decided_at is None:
            decision.decided_at = datetime.utcnow()
        decision_repo.save(decision)

    log.info("outcome recorded: decision %s → %s (delta=%.2f)",
             payload.decision_id, payload.outcome_type, delta or 0)
    return outcome


def _calculate_confidence_delta(
    decision: PhantDecision,
    outcome_type: str,
    metric_expected: Dict[str, Any],
    metric_actual: Dict[str, Any],
) -> Optional[float]:
    """
    Confidence delta logic:

    1. If both metric dicts have a "value" key, compute ratio (actual/expected - 1.0)
       and cap to [-1.0, 1.0]. Positive = exceeded expectations; negative = fell short.

    2. If PHANT made a recommendation (phant_recommendation is set), factor in
       whether the founder agreed and what the outcome was:
         - PHANT recommended this AND outcome is success   → large positive signal
         - PHANT recommended this AND outcome is failure   → negative signal
         - Founder overrode PHANT AND outcome is success   → negative (PHANT was wrong)
         - Founder overrode PHANT AND outcome is failure   → positive (PHANT was right to warn)

    3. Fallback — qualitative mapping from outcome_type alone if no metrics or
       no PHANT recommendation is on record.

    Returns None if there is genuinely not enough signal to compute a delta.
    """
    # ── 1. Metric-based delta ────────────────────────────────────────────────
    exp_val = metric_expected.get("value") if metric_expected else None
    act_val = metric_actual.get("value") if metric_actual else None
    metric_delta: Optional[float] = None
    if exp_val is not None and act_val is not None:
        try:
            e = float(exp_val)
            a = float(act_val)
            if e != 0:
                metric_delta = max(-1.0, min(1.0, (a / e) - 1.0))
        except (TypeError, ValueError):
            pass

    if metric_delta is not None:
        return round(metric_delta, 4)

    # ── 2. PHANT recommendation signal ───────────────────────────────────────
    if decision.phant_recommendation and decision.founder_agreed is not None:
        phant_was_right = (
            (decision.founder_agreed and outcome_type in ("success", "partial")) or
            (not decision.founder_agreed and outcome_type == "failure")
        )
        phant_was_wrong = (
            (decision.founder_agreed and outcome_type == "failure") or
            (not decision.founder_agreed and outcome_type == "success")
        )
        if phant_was_right:
            return 0.4 if outcome_type == "partial" else 0.7
        if phant_was_wrong:
            return -0.5

    # ── 3. Qualitative fallback ───────────────────────────────────────────────
    fallback = {
        "success": 0.5,
        "partial": 0.1,
        "failure": -0.5,
        "unexpected": 0.0,
    }
    return fallback.get(outcome_type)


def list_decisions_with_outcomes(
    db: Session,
    owner_user_id: int,
    *,
    context_id: Optional[str] = None,
    domain: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Tuple[PhantDecision, Optional[PhantOutcome]]]:
    """Return [(decision, latest_outcome_or_None)] for the Intelligence view."""
    return DecisionRepository(db).with_outcome_status(owner_user_id, limit=limit)


def calibration_summary(db: Session, owner_user_id: int) -> Dict[str, Any]:
    """
    Aggregate the calibration signal across all outcomes with a confidence_delta.
    Used by the brief and the intelligence view to answer: "Is PHANT's advice
    tracking with reality?"
    """
    outcomes = OutcomeRepository(db).calibration_sample(owner_user_id)
    if not outcomes:
        return {"sample_size": 0, "mean_delta": None, "accuracy_signal": "insufficient_data"}

    deltas = [o.confidence_delta for o in outcomes if o.confidence_delta is not None]
    if not deltas:
        return {"sample_size": len(outcomes), "mean_delta": None, "accuracy_signal": "insufficient_data"}

    mean = sum(deltas) / len(deltas)
    positive = sum(1 for d in deltas if d > 0.1)
    negative = sum(1 for d in deltas if d < -0.1)

    signal = "tracking"
    if mean > 0.3:
        signal = "calibrated_positive"
    elif mean < -0.3:
        signal = "miscalibrated"
    elif positive == 0 and negative == 0:
        signal = "neutral"

    return {
        "sample_size": len(deltas),
        "mean_delta": round(mean, 3),
        "positive_outcomes": positive,
        "negative_outcomes": negative,
        "accuracy_signal": signal,
    }
