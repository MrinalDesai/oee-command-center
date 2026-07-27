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
- RESULT: MAD CTE failed at runtime as predicted (window-in-aggregate);
CoCo restructured into sequential CTEs. First proc version consumed the
stream before processing — failed call ate a 4,080-row batch; proc
rebuilt consume-last with PROCESSED_BATCH_LOG audit. Verdict run:
AST-007 flagged BEARING_WEAR / HIGH — vib 11.02 vs 3.41 baseline
(z=33.2, slope 1.67/day), temp 80.9°C (z=10.1) confirming the coupled
signature. 11 other assets silent. 576 rows processed and receipted.
days_to_threshold=0 noted (asset already past alarm line — demo staging
item for G3).

## Learned
- All SQL files authored fully qualified from now on; no session context
  assumed anywhere, including proc internals (task runtime context differs).
- Approval tiers: schema-scoped session grants are the right granularity.

## Screenshot
![session](./img/01-detection-deploy.png)



