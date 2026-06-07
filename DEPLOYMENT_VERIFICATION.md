# MyTodo Founder OS — Deployment Verification
# Fill in each field after deployment completes.

## Deployment

| Field | Value |
|-------|-------|
| URL | https://mytodo-gold-kappa.vercel.app |
| Vercel project | mytodo |
| Deployment timestamp | _fill in_ |
| Git commit | _fill in_ |
| Branch | main |

## Pre-flight checklist

Run these checks before confirming deployment success.

### 1. Environment variables (Vercel → mytodo → Settings → Environment Variables)

| Variable | Required | Status |
|----------|----------|--------|
| `DATABASE_URL` | YES — Neon PostgreSQL connection string | [ ] set |
| `MYTODO_ACCESS_CODE` | YES — replace default "humble" | [ ] set |
| `MYTODO_COOKIE_SECRET` | YES — `openssl rand -hex 32` | [ ] set |
| `PHANG_ADMIN_SECRET` | YES — same value as VPS gateway | [ ] set |
| `DEEPSEEK_API_KEY` | YES — Copilot AI requires this | [ ] set |
| `MYTODO_OWNER_EMAIL` | optional — defaults to admin@infopro.ng | |
| `MYTODO_OWNER_NAME` | optional — defaults to Boluwatife | |
| `GATEWAY_URL` | optional — defaults to https://api.infopro.ng | |

### 2. Neon PostgreSQL setup

1. Create project at https://neon.tech (free tier)
2. Copy connection string (format: `postgresql://user:pass@host/dbname?sslmode=require`)
3. Paste as `DATABASE_URL` in Vercel

### 3. Health check

```bash
curl -s https://mytodo-gold-kappa.vercel.app/health
```

Expected: `{"status":"ok","service":"mytodo-founder-os"}`

| Check | Expected | Result |
|-------|----------|--------|
| GET /health | 200 `{"status":"ok","service":"mytodo-founder-os"}` | _fill in_ |
| GET /login | 200 (login page renders) | _fill in_ |
| POST /login (correct code) | 303 redirect to /copilot | _fill in_ |
| GET /copilot (authenticated) | 200 (chat UI renders) | _fill in_ |

### 4. Migration status

Migrations run automatically at startup via `init_db()`.
Tables created: `initiatives`, `tasks`, `revenue_records`, `distribution_actions`, `reflections`, `daily_briefs`, `chat_messages`

Verify with Neon console → Tables tab.

### 5. Startup log check

In Vercel → mytodo → Functions → View logs:

Expected lines:
```
MyTodo Founder OS started — database ready
```

No expected errors. If `psycopg2` fails, check that DATABASE_URL starts with `postgresql://` not `postgres://` (database.py normalises this automatically).

## Deploy command

```bash
# From products/mytodo/ directory, or push to git and let Vercel auto-deploy
vercel --prod
```

## Rollback

If deployment fails, Vercel keeps the previous deployment active.
Dashboard → mytodo → Deployments → Promote previous deployment.

## Status

- [ ] Env vars set
- [ ] Health endpoint 200
- [ ] Login works
- [ ] Copilot page renders
- [ ] Database tables created
- [ ] Deployment timestamp recorded above
