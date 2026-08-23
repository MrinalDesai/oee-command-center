# AGENTS.md — how agents operate this repository

## Identity
ForgePulse: predictive maintenance + OEE command center on Snowflake.
Account objects live in OEE_DB (OT / ERP / ANALYTICS / CONTAINERS).

## Doctrine (binding)
Rules own safety. Retrieval owns grounding. The model owns reasoning.
- Deterministic rules are the severity/action floor; models never override.
- Every number in generated text must trace to a query result.
- SENSOR_FAULT (FP-03) never dispatches parts.
- Idempotency: one open event per asset+mode (NEW/INVESTIGATING/ACTIONED block).

## Conventions
- Fully qualified names in ALL SQL (OEE_DB.SCHEMA.OBJECT).
- Credentials only via environment variables / scripts/env.ps1 (git-ignored).
  Never write credentials into files, code, or chat.
- Tasks: resume children-first (ACT, DIAGNOSE, DETECT); suspend DETECT_TASK
  between sessions. Suspend FORGEPULSE_CONSOLE service when not demoing.
- Generated data (data/) is reproducible from src/generate_telemetry.py and
  is not committed.

## Skills
skills/failure-prediction · skills/rca-investigation ·
skills/work-order-dispatch — see each SKILL.md for data sources and rules.

## Deploy
Full redeploy: docs/redeploy.md (rehearsed; ~1 hour via one CoCo prompt).
Console image: forgepulse-ui/Dockerfile -> account image repository ->
sql/02_create_service.sql. Never DROP the service after URL freeze —
suspend/resume only.
