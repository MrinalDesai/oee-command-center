# Redeploy Runbook — Fresh Account to Running Demo

Purpose: trial accounts expire ~Aug 25. G4 (Aug 24) opens by executing this
end to end on a fresh account. Target: < 1 hour. Every manual step taken in
dev must be reflected here (and in scripts/) the same day it happens.

## 1. Accounts

1. CoCo trial signup (the $40 CoCo + $360 platform bundle — the page with
   the $400 pricing text; NOT the generic snowflake.com trial). Fresh email.
   AWS · US West (Oregon) · Enterprise.
2. Optionally a second generic trial for SQL-side free credits (day-1
   pattern: Agent on subscribed acct, SQL on free acct). Decide at G4
   whether one account suffices for the demo window.
3. Card armor on any card-linked account, immediately:
```sql
CREATE RESOURCE MONITOR CARD_GUARD WITH CREDIT_QUOTA = 3
  TRIGGERS ON 100 PERCENT DO SUSPEND_IMMEDIATE;
ALTER ACCOUNT SET RESOURCE_MONITOR = CARD_GUARD;
```
   Cancel subscription auto-renewal same day (trial persists to end date).

## 2. Account prep (each account, ACCOUNTADMIN)

```sql
ALTER ACCOUNT SET CORTEX_MODELS_ALLOWLIST = 'All';
CALL SNOWFLAKE.MODELS.CORTEX_BASE_MODELS_REFRESH();  -- takes minutes
ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';
```
Do NOT touch CORTEX_CODE_* limit parameters (defaults are correct;
setting CLI limit manually caused the day-1 lockout).

## 3. CLI wiring

- `cortex` → wizard → agent account (sync from browser session — make sure
  ONLY the intended account is logged in at app.snowflake.com) → same for
  SQL? answer per split decision → verify banner shows both slots correct.
- connections.toml is the source of truth; hand-editable
  (account = org-acct identifier; authenticator = externalbrowser works).
- Launch cortex FROM the project folder (trust scope), never from home dir.

## 4. Build the system (order matters)

1. sql/01_schema.sql        — DB, schemas, warehouse, 8 tables
2. python src/generate_telemetry.py  (seeded — identical data every run)
3. Load CSVs: stage + PUT + COPY (CoCo one-shot prompt; verify counts:
   1,244,160 / 12 / 41 / 10 / 810)
4. sql/02_streams.sql       — append-only stream (do NOT recreate later;
   streams hold state)
5. sql/03_detection.sql     — proc + task (task starts SUSPENDED)
6. Manual CALL DETECT_ANOMALIES() → verify AST-007 flagged, 11 silent
7. ALTER TASK ... RESUME    — only after 6 passes
8. [G1.5+] document pipeline, semantic view, agent, notebook/registry,
   Streamlit — append steps here as they are built
9. Kafka: docker start kafka; producer + consumer for live feed segments

## 5. Verify

- Row counts match §4.3
- Stream: SYSTEM$STREAM_HAS_DATA after a producer run
- Events: AST-007 HIGH BEARING_WEAR with days_to_threshold + feature_json
- [append per-stage checks as built]

## Known traps (all hit once already)

- Statement-level context loss in CoCo: fully qualify ALL object names
- Browser multi-session: wizard syncs whatever app.snowflake.com is
  logged into
- CREATE OR REPLACE STREAM discards pending state
- Compute pools bill while running: create suspended, drop after tests
- New Snowsight worksheets have no database context
