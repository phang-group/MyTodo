# AI Life Assistant — Professional Edition v2.0 (MVP)

## Overview
A privacy-first, on-device executive assistant for email, Slack, calendar, and files. All processing is local. No data leaves your device. All actions require human approval.

## Core MVP Features
- Local data ingestion (mocked for MVP)
- Injection filter for all inbound content
- Local semantic indexing and search
- Classification and summarization pipeline
- Approval Queue UI (local web app)
- Secure, auditable storage and retention enforcement
- Encrypted logging

## Directory Structure
- `services/` — Python microservices (ingestion, filter, index, approval queue)
- `webui/` — Minimal local web UI for approval queue
- `data/` — Local, encrypted data store
- `logs/` — Encrypted audit logs
- `config/` — Configuration files

## Security
- All services run locally, isolated (Docker recommended)
- No network access except localhost
- All logs and data encrypted at rest
- No autonomous outbound actions

## Setup
1. Install Docker and Docker Compose
2. Build and run: `docker compose up --build`
3. Access Approval Queue UI at `http://localhost:8080`

## Developer Notes
- All code is Python (backend) and minimal JS/HTML (frontend)
- See `services/` for service entrypoints
- See `webui/` for UI code
