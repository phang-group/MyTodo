"""
Founder AI Copilot — natural language → system state.

Pipeline:
  User message
  → intent + entity extraction (DeepSeek)
  → state update (DB write)
  → distribution generation if build work detected
  → response text

The copilot never just responds — it always acts on what it hears.
"""

import json
import logging
import os
from datetime import date, datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

import models

log = logging.getLogger("mytodo.copilot")

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ── Intent extraction ─────────────────────────────────────────────────────────

INTENT_SYSTEM = """You are the AI copilot for MyTodo Founder OS — a tool used by Boluwatife Faturoti,
a solo founder running multiple AI products in Nigeria:
- InfoPro (AI academic writing tool at infopro.ng)
- NextDoor NG (real estate + WhatsApp marketplace at nextdoorhome.site)
- PHANG Store (ecosystem hub at phang.store)
- CUA (internal AI ops agent)
- Any new initiatives the founder mentions

Your job: extract structured intent and entities from the founder's message.

INTENT types:
  CREATE_INITIATIVE    — starting or founding something new
  UPDATE_PROGRESS      — completed work, built something, shipped a feature
  RECORD_REVENUE       — earned money, got paid, made a sale, received payment
  RECORD_DISTRIBUTION  — published, posted, shared, promoted something
  CREATE_TASK          — todo, reminder, something to do later
  DAILY_PLANNING       — asking for priorities, "what should I focus on?", "what's next?"
  GENERAL_CONTEXT      — sharing context with no immediate action (e.g., "I'm moving to Canada")
  UNKNOWN              — cannot determine intent

Currency normalisation: convert GBP/USD to NGN estimate if needed (1 GBP ≈ 2000 NGN, 1 USD ≈ 1600 NGN).

Output ONLY valid JSON — no markdown, no explanation:
{
  "intent": "<INTENT>",
  "confidence": <0-100>,
  "initiative_name": "<name or null — be specific: 'Foodie AI' not 'my project'>",
  "entities": {
    "description": "<what was done/built/posted/sold — be specific>",
    "amount_ngn": <number or null — revenue amount in NGN>,
    "channel": "<x_post|reddit|youtube|devlog|whatsapp_broadcast|linkedin|producthunt|newsletter|other or null>",
    "task_title": "<task text or null>",
    "build_delta": <suggested build score increase 1-15, or null — only for UPDATE_PROGRESS>,
    "context_note": "<any important context for future reference>"
  },
  "generate_distribution": <true if founder completed build work and distribution should be suggested>,
  "response_hint": "<tone: encouraging|factual|strategic>",
  "requires_clarification": <true only if truly ambiguous>
}"""

DISTRIBUTION_SYSTEM = """You are PHANT — the intelligence layer for PHANG Technologies.

A founder just completed build work on one of their products. Suggest 3-4 distribution actions
they should take in the next 48 hours. Be specific to the Nigerian/African tech ecosystem.

Channels available: x_post, reddit, youtube, devlog, whatsapp_broadcast, linkedin, producthunt, newsletter, other

Output ONLY valid JSON:
{
  "actions": [
    {
      "channel": "<channel>",
      "description": "<specific: what to post, which subreddit, what angle — not generic>",
      "priority": "<high|medium>"
    }
  ]
}"""

BRIEF_SYSTEM = """You are PHANT — the intelligence layer for PHANG Technologies.

Generate a concise Daily Founder Brief for Boluwatife, a solo founder running multiple AI products.
The brief routes his attention: what matters today, what to do, what's blocked.

Key insight: most projects are overbuilt and underdistributed. The bottleneck is almost always distribution.

Output ONLY valid JSON:
{
  "top_priority": {
    "initiative": "<name>",
    "reason": "<why this is top priority today — 1 sentence>",
    "bottleneck": "<build|distribution|revenue>"
  },
  "actions": [
    "<specific action 1>",
    "<specific action 2>",
    "<specific action 3>"
  ],
  "revenue_opportunities": [
    "<specific opportunity 1>",
    "<specific opportunity 2>"
  ],
  "blocked_initiatives": [
    {"name": "<initiative>", "blocker": "<what's blocking it>"}
  ],
  "phant_confidence": <50-95 — how confident PHANT is given available data>,
  "headline": "<one sentence: the single most important thing for the founder to know today>"
}"""


async def _call_deepseek(system: str, user: str, max_tokens: int = 800) -> Optional[dict]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            return json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception as e:
        log.warning("[copilot] DeepSeek call failed: %s", e)
        return None


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def process_message(
    message: str,
    db: Session,
    user_id: int,
) -> dict:
    """
    Full copilot pipeline.

    Returns:
        {
          "response": str,           — message to show the user
          "actions_taken": list,     — list of {type, description} dicts
          "intent": str,
          "show_brief": bool,        — True if DAILY_PLANNING intent
        }
    """
    actions_taken = []

    # Step 1 — Extract intent and entities
    parsed = await _call_deepseek(INTENT_SYSTEM, message)
    if not parsed:
        return {
            "response": "I could not process that right now. DeepSeek API key may not be configured.",
            "actions_taken": [],
            "intent": "UNKNOWN",
            "show_brief": False,
        }

    intent = parsed.get("intent", "UNKNOWN")
    entities = parsed.get("entities", {})
    initiative_name = parsed.get("initiative_name")
    requires_clarification = parsed.get("requires_clarification", False)

    if requires_clarification:
        return {
            "response": f"Could you be more specific? I detected intent: {intent}, but I need more detail to act on it.",
            "actions_taken": [],
            "intent": intent,
            "show_brief": False,
        }

    # Step 2 — Resolve or create initiative if mentioned
    initiative = None
    if initiative_name:
        initiative = _find_or_create_initiative(db, initiative_name, user_id)

    # Step 3 — Execute the intent
    if intent == "CREATE_INITIATIVE":
        if not initiative:
            initiative = models.Initiative(
                gateway_user_id=user_id,
                name=initiative_name or entities.get("description", "New Initiative"),
                description=entities.get("context_note", ""),
                stage="ideation",
            )
            db.add(initiative)
            db.commit()
            db.refresh(initiative)
        actions_taken.append({
            "type": "initiative_created",
            "description": f"Created initiative: {initiative.name}",
        })
        response = (
            f"Initiative *{initiative.name}* created.\n"
            f"Build: 0% · Distribute: 0% · Revenue: 0%\n\n"
            f"What's the first thing you're building?"
        )

    elif intent == "UPDATE_PROGRESS":
        if initiative:
            delta = entities.get("build_delta") or 5
            delta = max(1, min(15, int(delta)))
            old_score = initiative.build_score or 0
            initiative.build_score = min(100, old_score + delta)
            initiative.bottleneck = initiative.compute_bottleneck()
            initiative.updated_at = datetime.utcnow()
            db.commit()
            actions_taken.append({
                "type": "progress_updated",
                "description": f"{initiative.name} build score: {old_score}% → {initiative.build_score}%",
            })

            # Generate distribution opportunities if build work completed
            if parsed.get("generate_distribution", False):
                dist_actions = await _generate_distribution(
                    db, user_id, initiative,
                    entities.get("description", "feature completed"),
                )
                actions_taken.extend(dist_actions)

            response = _build_progress_response(initiative, entities, actions_taken)
        else:
            # No initiative identified — create a task instead
            task = models.Task(
                gateway_user_id=user_id,
                title=entities.get("description", message[:80]),
                category="build",
                for_date=date.today(),
            )
            db.add(task)
            db.commit()
            actions_taken.append({"type": "task_created", "description": task.title})
            response = f"Noted. I've logged that as a completed build task.\n\nWhich initiative does this belong to?"

    elif intent == "RECORD_REVENUE":
        amount = entities.get("amount_ngn") or 0
        if amount > 0 and initiative:
            record = models.RevenueRecord(
                gateway_user_id=user_id,
                initiative_id=initiative.id,
                amount=amount,
                source="client_payment",
                notes=entities.get("description", ""),
            )
            db.add(record)
            initiative.revenue_total = (initiative.revenue_total or 0) + amount
            initiative.revenue_score = min(100, (initiative.revenue_score or 0) + 10)
            initiative.updated_at = datetime.utcnow()
            db.commit()
            actions_taken.append({
                "type": "revenue_recorded",
                "description": f"₦{amount:,.0f} recorded for {initiative.name}",
            })
            response = (
                f"Revenue recorded: *₦{amount:,.0f}* for *{initiative.name}*.\n"
                f"Total: ₦{initiative.revenue_total:,.0f}\n\n"
                f"That's a real signal. Keep going."
            )
        else:
            response = (
                f"I need an amount and an initiative to record revenue.\n"
                f"Try: \"Made ₦50,000 from InfoPro\" or \"Got £200 from a client for Foodie AI\""
            )

    elif intent == "RECORD_DISTRIBUTION":
        channel = entities.get("channel") or "other"
        description = entities.get("description", message[:100])
        action = models.DistributionAction(
            gateway_user_id=user_id,
            initiative_id=initiative.id if initiative else None,
            channel=channel,
            description=description,
            status="completed",
            ai_suggested=False,
            completed_at=datetime.utcnow(),
        )
        db.add(action)
        if initiative:
            initiative.distribution_score = min(100, (initiative.distribution_score or 0) + 5)
            initiative.bottleneck = initiative.compute_bottleneck()
            initiative.updated_at = datetime.utcnow()
        db.commit()
        actions_taken.append({
            "type": "distribution_logged",
            "description": f"{channel} for {initiative.name if initiative else 'general'}",
        })
        ini_note = f" for *{initiative.name}*" if initiative else ""
        response = (
            f"Distribution action logged{ini_note}: *{channel}*.\n"
            f"{'Distribution score: ' + str(initiative.distribution_score) + '%' if initiative else ''}\n\n"
            f"What was the response?"
        )

    elif intent == "CREATE_TASK":
        task_title = entities.get("task_title") or entities.get("description") or message[:80]
        task = models.Task(
            gateway_user_id=user_id,
            initiative_id=initiative.id if initiative else None,
            title=task_title,
            category="ops",
            priority="high",
            for_date=date.today(),
        )
        db.add(task)
        db.commit()
        actions_taken.append({"type": "task_created", "description": task_title})
        response = f"Task added: *{task_title}*"
        if initiative:
            response += f"\nLinked to: {initiative.name}"

    elif intent == "DAILY_PLANNING":
        return {
            "response": "",  # will be overridden by daily brief
            "actions_taken": [],
            "intent": "DAILY_PLANNING",
            "show_brief": True,
        }

    elif intent == "GENERAL_CONTEXT":
        note = entities.get("context_note") or message
        response = (
            f"Context noted: _{note}_\n\n"
            f"This will inform PHANT's recommendations. "
            f"Is there a specific initiative this relates to?"
        )

    else:
        response = (
            f"I'm not sure what action to take with that. Try being more specific:\n\n"
            f"• \"I finished X feature on Foodie AI\"\n"
            f"• \"Made ₦30,000 from InfoPro\"\n"
            f"• \"Posted on Reddit about NextDoor\"\n"
            f"• \"What should I focus on today?\""
        )

    # Emit gateway event (fire and forget)
    await _emit_event(intent, {
        "user_id": user_id,
        "initiative": initiative.name if initiative else None,
        "actions": [a["type"] for a in actions_taken],
    })

    return {
        "response": response,
        "actions_taken": actions_taken,
        "intent": intent,
        "show_brief": False,
    }


async def generate_daily_brief(db: Session, user_id: int) -> dict:
    """Generate today's brief from current initiative state."""
    initiatives = (
        db.query(models.Initiative)
        .filter_by(gateway_user_id=user_id, is_active=True)
        .all()
    )

    if not initiatives:
        return {
            "headline": "No initiatives yet. Start by telling me what you're building.",
            "top_priority": None,
            "actions": ["Add your first initiative: \"I'm building Foodie AI\""],
            "revenue_opportunities": [],
            "blocked_initiatives": [],
            "phant_confidence": 50,
        }

    # Prepare context for DeepSeek
    ini_context = "\n".join([
        f"- {i.name}: build={i.build_score}% dist={i.distribution_score}% rev={i.revenue_score}% "
        f"stage={i.stage} revenue=₦{i.revenue_total or 0:,.0f}"
        for i in initiatives
    ])

    today_tasks = (
        db.query(models.Task)
        .filter(
            models.Task.gateway_user_id == user_id,
            models.Task.for_date == date.today(),
            models.Task.status.in_(["open", "in_progress"]),
        )
        .count()
    )

    user_content = f"""Today: {date.today().isoformat()}

Initiatives:
{ini_context}

Open tasks today: {today_tasks}

Generate the daily founder brief."""

    brief = await _call_deepseek(BRIEF_SYSTEM, user_content, max_tokens=1000)
    if not brief:
        # Fallback: compute without AI
        brief = _compute_brief_fallback(initiatives)

    return brief


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_or_create_initiative(db: Session, name: str, user_id: int) -> Optional[models.Initiative]:
    """Find initiative by name (case-insensitive fuzzy match) or return None."""
    name_lower = name.lower().strip()
    all_ini = db.query(models.Initiative).filter_by(gateway_user_id=user_id, is_active=True).all()
    # Exact match first
    for ini in all_ini:
        if ini.name.lower() == name_lower:
            return ini
    # Partial match
    for ini in all_ini:
        if name_lower in ini.name.lower() or ini.name.lower() in name_lower:
            return ini
    return None


async def _generate_distribution(
    db: Session,
    user_id: int,
    initiative: models.Initiative,
    work_description: str,
) -> list[dict]:
    """Generate and store distribution action suggestions for completed build work."""
    user_content = f"""Initiative: {initiative.name}
Work completed: {work_description}
Current distribution score: {initiative.distribution_score}%

Suggest 3 distribution actions."""

    result = await _call_deepseek(DISTRIBUTION_SYSTEM, user_content, max_tokens=600)
    if not result:
        return []

    actions_created = []
    for action in result.get("actions", [])[:3]:
        dist = models.DistributionAction(
            gateway_user_id=user_id,
            initiative_id=initiative.id,
            channel=action.get("channel", "other"),
            description=action.get("description", ""),
            status="pending",
            ai_suggested=True,
        )
        db.add(dist)
        actions_created.append({
            "type": "distribution_suggested",
            "description": f"{action.get('channel')}: {action.get('description', '')[:60]}",
        })

    db.commit()
    return actions_created


def _build_progress_response(
    initiative: models.Initiative,
    entities: dict,
    actions_taken: list,
) -> str:
    lines = [f"Build progress updated for *{initiative.name}*"]
    lines.append(
        f"Build: {initiative.build_score}% · "
        f"Distribute: {initiative.distribution_score}% · "
        f"Revenue: {initiative.revenue_score}%"
    )

    dist_suggestions = [a for a in actions_taken if a["type"] == "distribution_suggested"]
    if dist_suggestions:
        lines.append(f"\nYou shipped. Here are {len(dist_suggestions)} distribution actions I've queued:")
        for a in dist_suggestions:
            lines.append(f"• {a['description']}")
        lines.append("\nSee /distribution to mark them done.")
    else:
        if initiative.build_score > initiative.distribution_score + 20:
            lines.append(
                f"\nBuild is {initiative.build_score - initiative.distribution_score}% ahead of distribution. "
                f"Consider posting about what you built."
            )

    return "\n".join(lines)


def _compute_brief_fallback(initiatives: list) -> dict:
    """No-AI fallback: compute brief from raw scores."""
    if not initiatives:
        return {"headline": "No initiatives.", "top_priority": None, "actions": [], "revenue_opportunities": [], "blocked_initiatives": [], "phant_confidence": 50}

    # Find initiative with largest gap between build and distribution
    worst_gap = sorted(initiatives, key=lambda i: (i.build_score or 0) - (i.distribution_score or 0), reverse=True)
    top = worst_gap[0] if worst_gap else initiatives[0]

    return {
        "headline": f"{top.name} needs distribution — build is {(top.build_score or 0) - (top.distribution_score or 0)}% ahead.",
        "top_priority": {
            "initiative": top.name,
            "reason": "Highest build-distribution gap.",
            "bottleneck": "distribution",
        },
        "actions": [
            f"Post about {top.name} on X or Reddit",
            f"Share a build update for {top.name}",
            "Check Distribution queue for pending actions",
        ],
        "revenue_opportunities": [
            f"Convert {top.name} users to paying customers" if (top.users_count or 0) > 0 else f"Find first paying user for {top.name}",
        ],
        "blocked_initiatives": [
            {"name": i.name, "blocker": "paused"}
            for i in initiatives if i.stage == "paused"
        ],
        "phant_confidence": 55,
    }


async def _emit_event(intent: str, payload: dict) -> None:
    """Fire-and-forget event to Gateway."""
    try:
        gateway = os.getenv("GATEWAY_URL", "https://api.infopro.ng")
        secret = os.getenv("PHANG_ADMIN_SECRET", "")
        if not secret:
            return
        event_type = {
            "CREATE_INITIATIVE": "MYTODO_GOAL_CREATED",
            "UPDATE_PROGRESS": "MYTODO_TASK_COMPLETED",
            "RECORD_REVENUE": "MYTODO_REVENUE_RECORDED",
            "RECORD_DISTRIBUTION": "MYTODO_DISTRIBUTION_COMPLETED",
        }.get(intent)
        if not event_type:
            return
        async with httpx.AsyncClient(timeout=4) as client:
            await client.post(
                f"{gateway}/internal/events",
                headers={"X-Admin-Secret": secret},
                json={"event": event_type, "service": "mytodo", "payload_json": payload, "severity": "info"},
            )
    except Exception:
        pass
