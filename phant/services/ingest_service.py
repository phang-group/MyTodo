"""
phant/services/ingest_service.py — Event → Signal(function) → Memory.

Memories are expensive; events are cheap and numerous. If every event became a
memory, 60%+ of the corpus would be noise and retrieval would collapse. So the
Signal layer is implemented here as a significance function, NOT a staging table.

V1 uses static significance rules (no event history required — important on
serverless). V2 can replace the rule set with a trained significance classifier
without changing this interface or adding a table.

Decision (Part 4): Event → Signal(function) → Memory. No compromise.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from .memory_service import create_memory

log = logging.getLogger("phant.ingest")

# Always worth remembering — these carry founder-level signal regardless of severity.
ALWAYS_SIGNIFICANT = {
    "revenue_recorded", "deal_closed", "conversion_recorded",
    "lead_qualified", "lead_lost",
    "article_published", "listing_approved", "listing_rejected",
    "user_approved", "member_created", "access_key_redeemed",
}

# Carry their own structured reasoning object → mapped to a typed memory.
TYPE_MAP = {
    # revenue / facts
    "revenue_recorded": "fact", "deal_closed": "fact", "conversion_recorded": "fact",
    # risks
    "traffic_drop": "risk", "content_queue_empty": "risk", "content_queue_low": "risk",
    "seo_alert": "risk", "service_health_degraded": "risk", "ai_extraction_failed": "risk",
    "listing_risk_detected": "risk", "lead_lost": "risk",
    # opportunities
    "traffic_spike": "opportunity", "lead_qualified": "opportunity",
    "keyword_ranking_improved": "opportunity",
    # commitments / goals
    "user_invited": "commitment",
}

# Pure operational chatter — never worth a memory on its own.
NEVER_SIGNIFICANT = {
    "health_check", "login", "logout", "cache_refresh", "heartbeat",
    "page_view", "copilot_message_sent", "daily_brief_generated",
}


def is_significant(event_type: str, severity: str) -> bool:
    et = (event_type or "").lower()
    if et in NEVER_SIGNIFICANT:
        return False
    if et in ALWAYS_SIGNIFICANT:
        return True
    if severity in ("warning", "critical"):
        return True
    if et in TYPE_MAP:
        return True
    return False


def _memory_type_for(event_type: str, severity: str) -> str:
    et = (event_type or "").lower()
    if et in TYPE_MAP:
        return TYPE_MAP[et]
    if severity == "critical":
        return "risk"
    return "observation"


def _confidence_for(memory_type: str, severity: str) -> tuple[float, bool]:
    """Return (confidence, is_verified). Facts from products are trusted; inferences are tentative."""
    if memory_type == "fact":
        return 0.92, True
    if memory_type == "risk":
        return 0.75, True
    if memory_type == "opportunity":
        return 0.7, True
    return 0.6, False  # observation — tentative until corroborated


async def ingest(db: Session, event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run one product event through the significance gate. Returns a small result
    dict so the caller (POST /phant/events) can report what PHANT did.
    """
    event_type = event.get("event_type", "")
    severity   = event.get("severity", "info")
    product    = event.get("product", "unknown")

    if not is_significant(event_type, severity):
        log.debug("event dropped (not significant): %s/%s", product, event_type)
        return {"significant": False, "memory_created": False}

    memory_type = _memory_type_for(event_type, severity)
    confidence, is_verified = _confidence_for(memory_type, severity)

    title = (event.get("title") or event_type).strip()
    desc  = (event.get("description") or "").strip()
    content = f"{title} — {desc}" if desc and len(desc) < 240 else title

    metadata = dict(event.get("metadata") or {})
    metadata.setdefault("event_type", event_type)
    metadata.setdefault("severity", severity)

    owner_user_id = int(metadata.get("user_id") or 1)  # founder is the default subject

    mem = await create_memory(
        db,
        owner_user_id=owner_user_id,
        content=content,
        memory_type=memory_type,
        product_source=product,
        confidence=confidence,
        is_verified=is_verified,
        metadata=metadata,
        source_event_id=str(metadata.get("source_event_id") or event.get("id") or ""),
    )
    log.info("event → memory: %s/%s → %s (%s)", product, event_type, mem.id, memory_type)
    return {"significant": True, "memory_created": True,
            "memory_id": mem.id, "memory_type": memory_type}
