# MyTodo Copilot — Validation Record

Run these conversations in order using the founder account only. Capture results for each.
This document is the evidence that PRIORITY 2 and PRIORITY 4 of the Finalization Sprint are complete.

Pre-condition: Deployment confirmed in DEPLOYMENT_STATUS.md.

---

## Test 1 — Create Initiative

**Input:** "I'm building Foodie AI."

| Field | Expected | Actual |
|-------|----------|--------|
| Detected intent | `CREATE_INITIATIVE` | _fill_ |
| Initiative created in DB | Yes | _fill_ |
| Initiative name | "Foodie AI" | _fill_ |
| Build score | 0 | _fill_ |
| Distribution score | 0 | _fill_ |
| Revenue score | 0 | _fill_ |
| Gateway event emitted | `MYTODO_GOAL_CREATED` | _fill_ |
| Response tone | Encouraging, asks what you're building | _fill_ |

---

## Test 2 — Update Progress (triggers distribution generation)

**Input:** "I completed payment flow."

| Field | Expected | Actual |
|-------|----------|--------|
| Detected intent | `UPDATE_PROGRESS` | _fill_ |
| Initiative matched | Foodie AI | _fill_ |
| Build score delta | +5 to +15 | _fill_ |
| Distribution actions generated | 3 (ai_suggested=True) | _fill_ |
| Distribution actions channels | e.g. x_post, reddit, devlog | _fill_ |
| Gateway event emitted | `MYTODO_TASK_COMPLETED` | _fill_ |
| Response includes distribution queue notice | Yes | _fill_ |

Verify distribution actions visible at /distribution.

---

## Test 3 — Record Distribution

**Input:** "I posted Foodie AI on Reddit."

| Field | Expected | Actual |
|-------|----------|--------|
| Detected intent | `RECORD_DISTRIBUTION` | _fill_ |
| Channel detected | `reddit` | _fill_ |
| Distribution action created (status=completed) | Yes | _fill_ |
| Distribution score increased | +5 | _fill_ |
| Gateway event emitted | `MYTODO_DISTRIBUTION_COMPLETED` | _fill_ |

---

## Test 4 — Record Revenue

**Input:** "I made ₦50,000 from a client."

| Field | Expected | Actual |
|-------|----------|--------|
| Detected intent | `RECORD_REVENUE` | _fill_ |
| Amount parsed | 50000 | _fill_ |
| Revenue record created | Yes | _fill_ |
| Initiative.revenue_total updated | +50000 | _fill_ |
| Revenue score increased | +10 | _fill_ |
| Gateway event emitted | `MYTODO_REVENUE_RECORDED` | _fill_ |

---

## Test 5 — Daily Planning

**Input:** "What should I focus on today?"

| Field | Expected | Actual |
|-------|----------|--------|
| Detected intent | `DAILY_PLANNING` | _fill_ |
| Brief generated | Yes | _fill_ |
| Headline present | Yes | _fill_ |
| Top priority identifies Foodie AI | Yes (highest build-dist gap) | _fill_ |
| Actions list non-empty | Yes (3+ items) | _fill_ |
| Revenue opportunities listed | Yes | _fill_ |
| Brief page (/daily-brief) also loads | Yes | _fill_ |

---

## PHANT Signal Verification (Priority 3)

After running all 5 tests, verify PHANT received the signals.

On VPS:
```bash
docker exec -it phang-postgres-1 psql -U phang -d phang -c "
SELECT event, service, created_at FROM phang_events
WHERE event LIKE 'MYTODO_%'
ORDER BY created_at DESC LIMIT 10;"
```

| Event | Appeared in phang_events? |
|-------|--------------------------|
| MYTODO_GOAL_CREATED | _fill_ |
| MYTODO_TASK_COMPLETED | _fill_ |
| MYTODO_DISTRIBUTION_COMPLETED | _fill_ |
| MYTODO_REVENUE_RECORDED | _fill_ |

PHANT signal classification (wait up to 60s after events land):
```bash
docker exec -it phang-cua-1 python3 -c "
import asyncio, asyncpg, os
async def check():
    pool = await asyncpg.create_pool(os.getenv('POSTGRES_DSN'))
    rows = await pool.fetch(\"SELECT signal_type, priority, created_at FROM phant_signals WHERE signal_type LIKE 'MYTODO_%' ORDER BY created_at DESC LIMIT 10\")
    for r in rows: print(dict(r))
asyncio.run(check())"
```

| Signal type | In phant_signals? | Priority |
|-------------|------------------|---------|
| MYTODO_GOAL_CREATED | _fill_ | low |
| MYTODO_TASK_COMPLETED | _fill_ | low |
| MYTODO_DISTRIBUTION_COMPLETED | _fill_ | medium |
| MYTODO_REVENUE_RECORDED | _fill_ | critical |

---

## Mobile Test (Priority 6)

Open https://mytodo-gold-kappa.vercel.app on phone browser.

| Check | Pass? |
|-------|-------|
| Login page displays correctly | _fill_ |
| Copilot page: bottom nav visible | _fill_ |
| Copilot page: input not hidden by keyboard | _fill_ |
| Chat message sent and response received | _fill_ |
| Daily Brief page loads on mobile | _fill_ |
| No horizontal scrolling on any page | _fill_ |
| Initiative cards readable on mobile | _fill_ |

---

## Sprint Complete Checklist

- [ ] MyTodo is live (DEPLOYMENT_STATUS.md filled)
- [ ] All 5 copilot tests passed
- [ ] Distribution actions generated automatically on build update
- [ ] Events appear in phang_events on VPS
- [ ] PHANT classifies MYTODO_* signals
- [ ] Daily Brief generates from real initiative data
- [ ] Mobile experience passes all checks
- [ ] 6h Telegram reminders active (requires CUA redeploy with MYTODO_URL env var)

Validated by: _Boluwatife Faturoti_  
Validated at: _fill_
