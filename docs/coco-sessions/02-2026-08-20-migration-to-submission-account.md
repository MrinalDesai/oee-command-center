# CoCo session receipt 02 — full migration to the submission account
**Date:** 2026-08-20 · **Account:** DMXGSFN-EYB14592 · **Screenshots:** `img/Screenshot 2026-08-20 *.png`

## What was asked
One batched prompt per `docs/redeploy.md` §4: schema → local telemetry
generation → stage/PUT/COPY with count verification → streams → detection
→ diagnose → act → fault-pattern catalog, tasks left suspended, then a
manual DETECT call.

## What CoCo did
- Created OEE_DB (OT/ERP/ANALYTICS), warehouse, 8 tables
- Loaded 1,244,160 / 12 / 41 / 10 / 810 rows — counts verified against
  the runbook's expected values
- Deployed streams, all three procedures, the serverless task DAG,
  FAULT_PATTERN_CATALOG; wired fault_pattern_id into detection
- Manual CALL → AST-007 / BEARING_WEAR / FP-01 / HIGH detected

## Incidents (and why they're the point)
1. **PowerShell @stage quoting** broke the snow-CLI upload path — CoCo
   self-diagnosed ("No snow CLI available. I'll use SQL PUT instead")
   and switched to SQL PUT. Worked.
2. **Unsupported correlated subquery** in the new fault-pattern insert —
   CoCo rewrote it as a LEFT JOIN, recreated the proc, synced the local
   file.
3. **Stream re-arm gone wrong:** CoCo inserted 12 improvised rows, then
   its identity-based cleanup DELETE over-fired (38,644 rows — identity
   ≠ insertion order under COPY). **CoCo detected its own error against
   the known-good count and recovered honestly**: truncate + clean
   reload from stage, verified back to exactly 1,244,160, event intact.

## Post-session
Autonomous verification same evening: 12 chained SUCCEEDED task runs
(DETECT→DIAGNOSE→ACT each minute); duplicate-alert bug surfaced by the
autonomy itself → idempotency fix (ACTIONED blocks re-alerting) deployed
to proc + file; duplicates cleaned to 1 event / 1 finding / 1 work order.
