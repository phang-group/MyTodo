"""
MyTodo AI Engine — DeepSeek strategic analysis.

Takes a user's goal + current state → returns structured strategic intelligence:
- Brutal likelihood assessment
- Blockers with severity
- Timeline reality check
- Phased roadmap
- Daily executable tasks
- Failure cascade visibility
- Best move today
"""

import json
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("mytodo.ai")

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

SYSTEM_PROMPT = """You are a brutal, honest strategic intelligence system.

Your job is NOT to motivate. Your job is to calculate reality.

When given a goal and a person's current state, you produce a structured strategic analysis that:
1. Honestly assesses the probability of success
2. Identifies the real blockers (not generic advice)
3. Checks if the timeline is realistic given current trajectory
4. Builds a phased execution roadmap
5. Defines the minimum daily actions required
6. Shows what failure cascades look like (consequences of inaction)
7. States the single best move today

Rules:
- Be specific, not generic. "Save more money" is useless. "Save ₦47,000/month for 14 months" is useful.
- Do not soften assessments. If they will fail at current trajectory, say so clearly.
- Reference actual numbers from their state.
- Output ONLY valid JSON. No markdown, no text outside the JSON.

Output schema:
{
  "likelihood_score": <0-100 integer>,
  "honest_assessment": "<2-3 sentence brutal reality check>",
  "blockers": [
    {"blocker": "<specific blocker>", "severity": "<critical|high|medium>", "fix": "<specific action>"}
  ],
  "timeline": {
    "target": "<user's target>",
    "realistic": "<realistic timeline given current state>",
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
      "consequence_if_skipped": "<specific consequence>"
    }
  ],
  "failure_cascades": [
    {
      "trigger": "<what gets skipped>",
      "cascade": "<chain of consequences>",
      "probability_impact": "<e.g. -15% success probability>"
    }
  ],
  "best_move_today": "<single most important action right now and why>"
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
) -> dict:
    """Run DeepSeek analysis. Returns parsed dict or error dict."""
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

Analyse this goal against this reality. Be specific and honest."""

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
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_context},
                    ],
                    "max_tokens": 2000,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return json.loads(raw)
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

Original daily tasks:
{json.dumps(existing_analysis.get('daily_tasks', []), indent=2)}

Current blockers:
{json.dumps(existing_analysis.get('blockers', []), indent=2)}

Given the completion rate and days remaining, recalculate today's task list.
If completion rate is low, escalate priority and simplify tasks.
If on track, maintain or extend.

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
            # Accept either {"daily_tasks": [...]} or [...]
            if isinstance(parsed, list):
                return parsed
            return parsed.get("daily_tasks", existing_analysis.get("daily_tasks", []))
    except Exception as e:
        log.warning("[AI] Daily refresh failed: %s", e)
        return existing_analysis.get("daily_tasks", [])
