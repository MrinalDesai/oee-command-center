# SPCS Deployment Runbook — G4 Stretch (React/Three.js Command Center)

Status: entitlement VERIFIED on trial (compute pool created + dropped, day 1).
This is the Block 3 (Aug 24–30) runbook. Streamlit remains the committed UI;
this path is additive, never load-bearing. Names adapted to this project
(OEE_DB, OEE_* objects).

## Architecture

```
Browser → Snowflake-authenticated URL
  → SPCS service (single container)
      ├── React / Three.js frontend (built assets, bundled — NO CDNs)
      ├── FastAPI backend (serves frontend + /api/*)
      └── Snowflake connector (service OAuth token)
  → Snowflake (OEE_DB: views, tables, Cortex Agent/Search/Analyst)
```

## Key decisions (from review, 2026-07-26)

- Single container: frontend + backend together → no CORS, no browser creds
- Poll compact current-state views (10–30 s); no websockets
  (SPCS ingress has a 90 s inactivity timeout)
- Bundle ALL assets in the image (three.js, fonts, models, SVGs) —
  trial accounts block external egress
- Auth: service token at /snowflake/session/token + SNOWFLAKE_HOST/ACCOUNT
  env vars. NEVER a stored password/key in the container
- Service-owner execution for hackathon; caller's-rights noted as the
  production governance path in README
- Cost: AUTO_SUSPEND_SECS=300 on the pool; SUSPEND during dev,
  RESUME before demo

## Data contract (built in G2/G3, UI-agnostic — Streamlit uses the same)

Views in OEE_DB.APP:
- SENSOR_LATEST_VALUE, ASSET_HEALTH_CURRENT, ACTIVE_ALERTS,
  LINE_OEE_CURRENT, RECENT_PREDICTIONS, REPAIR_OBSERVATION_EVIDENCE

FastAPI endpoints map 1:1:
GET /api/assets · /api/assets/{id} · /api/telemetry/{id} · /api/alerts ·
/api/oee · /api/documents/{id} · POST /api/agent · /api/work-orders ·
/api/alerts/{id}/approve · GET /health

## Deployment sequence (G4)

1. Infra (ACCOUNTADMIN):
```sql
CREATE ROLE IF NOT EXISTS OEE_SPCS_ROLE;
GRANT BIND SERVICE ENDPOINT ON ACCOUNT TO ROLE OEE_SPCS_ROLE;
CREATE SCHEMA IF NOT EXISTS OEE_DB.CONTAINERS;
CREATE IMAGE REPOSITORY IF NOT EXISTS OEE_DB.CONTAINERS.OEE_REPOSITORY;
CREATE STAGE IF NOT EXISTS OEE_DB.CONTAINERS.SERVICE_SPECS
  DIRECTORY = (ENABLE = TRUE);
-- narrow grants: USAGE on OEE_DB + APP schema, SELECT on APP views,
-- INSERT/UPDATE only on action tables (WORK_ORDERS_GENERATED, event status)
```

2. Pool:
```sql
CREATE COMPUTE POOL IF NOT EXISTS OEE_UI_POOL
  MIN_NODES=1 MAX_NODES=1 INSTANCE_FAMILY=CPU_X64_XS
  AUTO_RESUME=TRUE AUTO_SUSPEND_SECS=300 INITIALLY_SUSPENDED=TRUE;
```

3. Build & push (from PC; linux/amd64 mandatory):
```
docker build --platform linux/amd64 -t oee-ui:latest .
snow spcs image-registry login
docker tag oee-ui:latest <org-acct>.registry.snowflakecomputing.com/oee_db/containers/oee_repository/oee-ui:latest
docker push  <same>
```

4. spec.yml: container (image, PORT=8000, resources 0.5–2 CPU / 1–4 Gi,
   readiness+liveness on /health), endpoint command-centre port 8000 public.

5. Service:
```sql
CREATE SERVICE OEE_COMMAND_CENTRE
  IN COMPUTE POOL OEE_UI_POOL
  FROM @OEE_DB.CONTAINERS.SERVICE_SPECS SPECIFICATION_FILE='spec.yml'
  MIN_INSTANCES=1 MAX_INSTANCES=1 QUERY_WAREHOUSE=OEE_WH;
SHOW ENDPOINTS IN SERVICE OEE_COMMAND_CENTRE;  -- → *.snowflakecomputing.app URL
```

6. Backend Snowflake client: oauth authenticator + token file read;
   QUERY_TAG='OEE_SPCS_UI'.

## Dockerfile shape
Multi-stage: node:22-alpine builds frontend (npm ci, npm run build) →
python:3.12-slim runtime, pip install backend requirements, copy dist,
uvicorn on :8000.

## Go/no-go at G4 open (Aug 24)
Pool creates on the FRESH account + redeploy clean + spine untouched by
freeze → build. Any of those false → Streamlit ships as recorded, this
doc stays for the finale story.
