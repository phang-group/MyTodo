# MyTodo

MyTodo is PHANG's internal founder operations repository. The active sub-project in this workspace is `ai-life-assistant/`.

## Purpose

This repository is for internal operating systems, founder productivity workflows, and privacy-sensitive assistant tooling. It is not intended for public launch in its current state.

## Status

**Phase:** internal tooling / exploratory build  
**Visibility:** private only  
**Operational posture:** local-first, privacy-first

## Architecture

Current active layout centers on `ai-life-assistant/`:

- `services/` for assistant microservices
- `webui/` for local review/approval UI
- `data/` for local state
- `logs/` for audit output
- `docker-compose.yml` for local orchestration

## Stack

- Python services
- local web UI
- Docker Compose
- local file-backed data/logging

## Roadmap Direction

Short-term:
- keep the repo private and deterministic
- improve local-only setup and secrets hygiene
- make the approval and audit path explicit

Medium-term:
- separate reusable internal tooling from personal operating workflows
- harden local encryption and retention handling

## Deployment Direction

There is no external deployment target right now. If deployed later, it should remain private, self-hosted, and local-network constrained.

## Environment

Use `.env.example` as a local template only. Real values stay off git.

## Never Commit

- personal data exports
- local assistant memory stores
- logs, transcripts, indexes, caches
- real secrets or encryption keys

## Folder Hygiene Suggestions

- keep the repo root as the private workspace boundary
- keep application code inside `ai-life-assistant/`
- treat `data/` and `logs/` as runtime-only and disposable
- do not mix founder-private material with reusable product code without an explicit split

## Safe Git Commands

```bash
git status
git remote -v
git checkout -b chore/repo-hygiene
git add README.md .gitignore .env.example
git diff --staged
git commit -m "docs: add private repo hygiene"
```

## Migration Notes

- remote repo can remain `MyTodo`
- keep this repository private even after other PHANG repos go public
- if internal tooling becomes reusable, extract it into a separate repo later rather than widening access here
