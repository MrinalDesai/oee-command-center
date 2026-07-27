# CoCo Session 01 — Detection Layer Deploy

**Date:** 2026-07-27 · **Surface:** CLI · **Connection:** Agent NBB14464 / SQL BMB76514

## Task given
Execute sql/03_detection.sql (ANOMALY_EVENTS schema upgrades, NOTIFICATIONS_LOG,
DETECT_ANOMALIES proc, DETECT_TASK), then one manual CALL and inspection of
ANALYTICS.ANOMALY_EVENTS.

## What happened
- CoCo split the file into per-statement executions; `USE DATABASE` did not
  persist across them → "no current database" failures on first pass.
- Instructed to fully qualify all object names (OEE_DB.ANALYTICS.* etc.,
  including inside the proc body and task definition); CoCo re-planned and
  re-ran with qualified names.
- Approval granted session-scoped: "any statement in OEE_DB.ANALYTICS"
  (+ equivalent for OT/ERP reads).
- RESULT: [fill in — proc return message, events inserted, whether the
  median/MAD CTE needed restructuring, false-positive check on other assets]

## Learned
- All SQL files authored fully qualified from now on; no session context
  assumed anywhere, including proc internals (task runtime context differs).
- Approval tiers: schema-scoped session grants are the right granularity.

## Screenshot
![session](./img/01-detection-deploy.png)
