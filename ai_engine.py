"""
MyTodo Cognitive Engine — DeepSeek strategic analysis.

Philosophy: help users understand reality better. NOT judge them against it.

The engine refines understanding progressively — it does not deliver verdicts.
Tone: strategic advisor. Not critic, not guru, not fake therapist.
"""

import json
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("mytodo.ai")

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ── Primary analysis prompt ────────────────────────────────────────────────────
# Core shift: from "brutal verdict" to "trajectory refinement".
# The system identifies constraints and leverage — not success/failure.
ANALYSIS_PROMPT = """You are a strategic intelligence system that helps people understand their trajectory clearly.

Your role is to map reality — not judge the person against it.

When given a goal and current state, produce a structured trajectory analysis that:
1. Estimates current probability given the actual data (not feelings)
2. Identifies the highest-leverage constraints to address first
3. Checks timeline feasibility against real numbers
4. Builds a phased execution path
5. Defines minimum executable daily actions
6. Surfaces what happens if critical actions are skipped (as data, not threat)
7. States the single highest-leverage move right now

Rules:
- Be specific, not generic. "Save more money" is useless. "Save ₦47,000/month for 14 months" is useful.
- Reference actual numbers from their state.
- Frame constraints as solvable problems, not character failures.
- Trajectory is not fixed — it changes with decisions. Make that visible.
- Do NOT use language like "you will fail", "this is impossible", "you're behind".
- DO use language like "current trajectory suggests", "the highest leverage shift is", "this constraint reduces probability by".
- Output ONLY valid JSON. No markdown, no text outside the JSON.

Output schema:
{
  "likelihood_score": <0-100 integer — current trajectory probability, not ceiling>,
  "trajectory_summary": "<2-3 sentences: where current trajectory leads, what's driving it, what changes it most>",
  "trajectory_confidence": <0-100 — how confident the model is given available information>,
  "momentum": "<building|stable|declining>",
  "blockers": [
    {"blocker": "<specific constraint>", "severity": "<critical|high|medium>", "fix": "<specific highest-leverage action>", "leverage_impact": "<e.g. +12% probability if resolved>"}
  ],
  "timeline": {
    "target": "<user's target>",
    "realistic": "<realistic timeline given current trajectory>",
    "gap_months": <integer — negative means ahead, positive means behind>,
    "on_track": <boolean>
  },
  "phases": [
    {
      "phase": <integer>,
      "title": "<phase name>",
      "duration": "<e.g. 3 months>",
      "milestones": ["<milestone>"],
      "success_criteria": "<measurable outcome>"
    }
  ],
  "daily_tasks": [
    {
      "task": "<specific daily action>",
      "time_required": "<e.g. 45 mins>",
      "priority": "<critical|high|medium>",
      "consequence_if_skipped": "<what changes in the trajectory>"
    }
  ],
  "constraint_cascades": [
    {
      "trigger": "<constraint that goes unaddressed>",
      "cascade": "<chain of trajectory effects>",
      "probability_impact": "<e.g. -15% probability over 3 months>"
    }
  ],
  "highest_leverage_move": "<single most trajectory-changing action right now and the specific reason why>"
}"""


# ── Reflection session prompt ──────────────────────────────────────────────────
# Progressive questioning — one domain at a time, building understanding.
REFLECTION_PROMPT = """You are a strategic thinking partner helping someone develop clarity about their goals.

Your role in a reflection session is to ask ONE focused question that deepens understanding.

You help people discover:
- What a goal actually represents to them (income? freedom? safety? identity?)
- What constraints are real vs perceived
- What assets they're underestimating
- What the highest-leverage 90-day action is

Rules:
- Ask ONLY one question. Never ask multiple at once.
- Questions should open up thinking, not lead to a specific answer.
- Do not assume you know what the person values — discover it.
- Vary the domain across sessions: motivation → constraints → assets → leverage → timeline
- Tone: curious, respectful, precise.
- Output ONLY valid JSON.

Output schema:
{
  "question": "<single focused question>",
  "domain": "<motivation|constraints|assets|leverage|timeline|identity>",
  "reasoning": "<why this question unlocks the most useful understanding right now>"
}"""


# ── Reflection processing prompt ───────────────────────────────────────────────
REFLECTION_ANALYSIS_PROMPT = """You are a strategic intelligence system processing a reflection answer.

Given a goal, the reflection question asked, and the person's answer, extract:
1. Any new constraints revealed
2. Any underestimated assets surfaced
3. Any motivation clarity gained
4. Updated trajectory implication
5. Whether the goal title/description needs refinement

Output ONLY valid JSON:
{
  "insights": ["<specific insight extracted>"],
  "new_constraints": ["<constraint revealed>"],
  "underestimated_assets": ["<asset surfaced>"],
  "trajectory_implication": "<how this answer shifts trajectory understanding>",
  "suggested_goal_refinement": "<null or a more precise goal statement>",
  "next_session_priority": "<motivation|constraints|assets|leverage|timeline|identity>"
}"""


async def analyse_goal(
    goal_title: str,
    goal_description: str,
    target_date: str,
    monthly_income: float,
    monthly_expenses: float,
    savings: float,
    skills: list[str],
    constraints: list[str],
    location: str,
    employment_type: str,
    notes: str = "",
    reflection_context: str = "",
) -> dict:
    """
    Run trajectory analysis. Returns parsed dict or error dict.
    reflection_context: optional summary of insights from reflection sessions.
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"error": "DEEPSEEK_API_KEY not set"}

    monthly_surplus = monthly_income - monthly_expenses
    user_context = f"""Goal: {goal_title}
Details: {goal_description or 'None provided'}
Target date: {target_date}

Current state:
- Location: {location}
- Employment: {employment_type}
- Monthly income: ₦{monthly_income:,.0f}
- Monthly expenses: ₦{monthly_expenses:,.0f}
- Monthly surplus: ₦{monthly_surplus:,.0f}
- Total savings: ₦{savings:,.0f}
- Skills: {', '.join(skills) if skills else 'Not specified'}
- Constraints: {', '.join(constraints) if constraints else 'None stated'}
- Additional context: {notes or 'None'}
{('- Reflection insights: ' + reflection_context) if reflection_context else ''}

Analyse this trajectory against this data."""

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": ANALYSIS_PROMPT},
                        {"role": "user", "content": user_context},
                    ],
                    "max_tokens": 2000,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            result = json.loads(raw)
            # Backward-compat alias: templates may read honest_assessment
            if "trajectory_summary" in result and "honest_assessment" not in result:
                result["honest_assessment"] = result["trajectory_summary"]
            if "highest_leverage_move" in result and "best_move_today" not in result:
                result["best_move_today"] = result["highest_leverage_move"]
            if "constraint_cascades" in result and "failure_cascades" not in result:
                result["failure_cascades"] = result["constraint_cascades"]
            return result
    except httpx.HTTPStatusError as e:
        log.error("[AI] DeepSeek HTTP error: %s %s", e.response.status_code, e.response.text[:200])
        return {"error": f"AI service error ({e.response.status_code})"}
    except json.JSONDecodeError as e:
        log.error("[AI] JSON parse failed: %s", e)
        return {"error": "AI returned malformed response"}
    except Exception as e:
        log.error("[AI] Unexpected error: %s", e)
        return {"error": str(e)}


async def refresh_daily_tasks(
    goal_title: str,
    existing_analysis: dict,
    completion_rate: float,
    days_remaining: int,
) -> list[dict]:
    """Recalculate today's tasks based on execution history."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return existing_analysis.get("daily_tasks", [])

    prompt = f"""Goal: {goal_title}
Days remaining to target: {days_remaining}
Recent task completion rate: {completion_rate:.0%}

Current daily tasks:
{json.dumps(existing_analysis.get('daily_tasks', []), indent=2)}

Current constraints:
{json.dumps(existing_analysis.get('blockers', []), indent=2)}

Given the completion rate and days remaining, recalculate today's task list.
If completion rate is low, simplify and reduce to the single highest-leverage action.
If on track, maintain or progress.

Return ONLY a JSON array of daily_task objects (same schema as input). No other text."""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "You output only valid JSON arrays. No markdown, no text."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 800,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
            return parsed.get("daily_tasks", existing_analysis.get("daily_tasks", []))
    except Exception as e:
        log.warning("[AI] Daily refresh failed: %s", e)
        return existing_analysis.get("daily_tasks", [])


async def generate_reflection_question(
    goal_title: str,
    goal_description: str,
    previous_sessions: list[dict],
    session_number: int,
) -> dict:
    """
    Generate the next progressive reflection question.
    previous_sessions: list of {question, domain, answer} from past sessions.
    Returns {question, domain, reasoning} or error dict.
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"error": "DEEPSEEK_API_KEY not set"}

    # Build session history summary
    history = ""
    if previous_sessions:
        history = "\n\nPrevious sessions:\n" + "\n".join(
            f"Session {i+1} [{s.get('domain','')}]: Q: {s.get('question','')} | A: {s.get('answer','')}"
            for i, s in enumerate(previous_sessions)
        )

    # Derive which domains are already covered
    covered = {s.get("domain", "") for s in previous_sessions}
    remaining = [d for d in ["motivation", "constraints", "assets", "leverage", "timeline", "identity"] if d not in covered]

    prompt = f"""Goal: {goal_title}
Description: {goal_description or 'None'}
Session number: {session_number}
Domains already explored: {', '.join(covered) if covered else 'none yet'}
Remaining domains to explore: {', '.join(remaining) if remaining else 'all covered — deepen most important'}
{history}

Generate the next reflection question."""

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": REFLECTION_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 300,
                    "temperature": 0.5,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return json.loads(raw)
    except Exception as e:
        log.warning("[AI] Reflection question generation failed: %s", e)
        return {"error": str(e)}


async def process_reflection_answer(
    goal_title: str,
    question: str,
    answer: str,
    previous_insights: list[str],
) -> dict:
    """
    Process a reflection answer to extract strategic insights.
    Returns {insights, new_constraints, underestimated_assets, trajectory_implication, ...}
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"insights": [], "trajectory_implication": ""}

    prompt = f"""Goal: {goal_title}

Question asked: {question}
Answer given: {answer}

Previously extracted insights:
{json.dumps(previous_insights) if previous_insights else '[]'}

Extract strategic intelligence from this answer."""

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": REFLECTION_ANALYSIS_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 500,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return json.loads(raw)
    except Exception as e:
        log.warning("[AI] Reflection processing failed: %s", e)
        return {"insights": [], "trajectory_implication": ""}
