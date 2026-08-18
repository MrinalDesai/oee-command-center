# ForgePulse UI — React command center (dev scaffold)

Frontend developed against a local mock backend serving the generator's CSVs.
Same API contract as the G4 SPCS deployment (docs/spcs-deployment.md) —
frontend runs unchanged when the real FastAPI/Snowflake backend replaces the mock.

## Run (two terminals, from repo root)

Backend (needs data/ to exist — run the generator first):
    cd forgepulse-ui/backend
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Frontend:
    cd forgepulse-ui/frontend
    npm install
    npm run dev        # http://localhost:5173 (proxies /api to :8000)

## Status
- S1 Plant Overview: built (KPI strip, 12-card health grid, sparklines w/
  baseline, critical pulse animation, click-through)
- S2 Triage: functional skeleton (queue + telemetry; finding card, evidence
  chips, approvals, NL bar land in G4)
- S3 OEE: functional skeleton (per-line table + WO history)
- Design tokens: BRD §8.1 exact. Reduced-motion respected; focus visible.
