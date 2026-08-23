# ForgePulse â€” Predictive Maintenance & OEE Command Center

**Snowflake CoCo CLI Hackathon 2026 â€” Predictive Maintenance and OEE Command Center**

A factory's machines stream sensor data into Snowflake. ForgePulse watches
that stream autonomously: it detects developing faults days before failure,
investigates the root cause against the plant's own repair history â€”
including scanned handwritten reports â€” creates the work order with parts
and a production-aware schedule, and shows a supervisor everything on a
live deployed console, with the projected OEE impact of acting early.

**Deployed console:** `https://etntyrb-dmxgsfn-eyb14592.snowflakecomputing.app` (Snowflake login required; served by
Snowpark Container Services from inside the submission account)

**Demo video:** `<VIDEO_URL>`

---

## The doctrine

> **Rules own safety. Retrieval owns grounding. The model owns reasoning.**

Every layer of ForgePulse follows this split:

- **Deterministic rules** decide what is a fault, what severity it carries,
  and what tier of action follows. No model can override the stuck-sensor
  floor or dispatch parts for an instrumentation error.
- **Retrieval** grounds every explanation: the RCA narrative may only cite
  numbers that exist in query results, and fleet history comes from actual
  work orders and actual scanned repair reports found by semantic search.
- **Models reason on top**: a registered XGBoost classifier adds pattern
  probability and explainable factors; a local LLM writes the narrative
  from the evidence dossier; a vision model reads the scanned paperwork.

## What happens, end to end

1. **Stream** â€” a Kafka producer emits 4 sensors Ã— 12 assets every 5
   seconds; a consumer lands batches in `OT.RAW_TELEMETRY`. A Snowflake
   **stream** marks the new rows.
2. **Detect (autonomous)** â€” a serverless **task** fires every minute, but
   only spends compute when the stream has data. The detection **procedure**
   computes engineered features (z-scores against each asset's own 28-day
   baseline, slopes, variance collapse, vibrationâ†’temperature lag
   correlation) and opens an `ANOMALY_EVENTS` row with a fault-pattern ID.
   Idempotency: one open event per asset+mode â€” an ACTIONED event blocks
   re-alerting (a rule added after the autonomous DAG itself surfaced the
   duplicate-alert bug; see `tests/test_idempotency.py`).
3. **Diagnose (autonomous)** â€” the next task in the DAG assembles the
   evidence dossier (features that fired, asset context, matching fleet
   work-order history) and writes a finding. A local LLM worker turns the
   dossier into a structured narrative: Observed â†’ Probable cause â†’
   Supporting history â†’ Urgency. Strict grounding: every number in the
   text traces to a table row.
4. **Enrich (explainability)** â€” a worker computes the same features the
   classifier was trained on, runs the **Model Registry** classifier for
   pattern probability, extracts SHAP top factors, embeds the symptoms and
   retrieves the three most similar past repairs from the scanned-report
   corpus by **VECTOR cosine similarity â€” the search runs inside
   Snowflake**.
5. **Act (autonomous)** â€” tier rules create the work order: parts checked
   against `SPARE_PARTS_INVENTORY`, the repair scheduled into the lowest-
   load window in `PRODUCTION_SCHEDULE`, notification logged. Sensor
   faults (FP-03) never dispatch parts.
6. **Show** â€” the deployed console renders it all: live waveforms whose
   display envelope is driven by real values against real baselines, the
   plant floor, the **AI Diagnosis panel** (verdict, confidence,
   top factors, similar past repairs with remedies and downtimes, and
   three evidence-backed questions a supervisor can click), and the
   **OEE bridge**: average unplanned downtime for this failure mode from
   history vs the planned 4-hour stop â†’ hours avoided â†’ availability and
   OEE deltas per line.

## The document layer

Twenty scanned, handwritten repair reports (generated with jitter,
rotation, and scan noise; ground truth in `reports/reports_index.csv`)
are read by a local vision model and validated field-by-field:
**100/100 key fields correct.** The extracted rows live in
`EXTRACTED_REPORTS`; bge-m3 embeddings of each report live in a
`VECTOR(FLOAT, 1024)` column, searched with `VECTOR_COSINE_SIMILARITY`
in plain SQL. Fleet learning made visible: a new fault on one machine
cites its siblings' repair paperwork.

## The classifier â€” an honest MLOps story

The fault classifier (XGBoost, 5 classes, registered in the **Model
Registry**) initially misfired in serving: 99% confident of belt slip on
a textbook bearing fault. Eight documented iterations followed â€” feature
train/serve skew, RPM regime mixture from production-schedule speed
changes, distribution shift from saturated faults the training sim never
contained, severity miscalibration â€” each diagnosed with evidence
(per-class feature means vs live values) and fixed at the root. Final
state: serving features computed with the exact training formulas; RPM
features excluded (documented data-regime limitation â€” FP-04 detection
remains rule-layer); the model now agrees with the rule layer at 98.9%
confidence, and the rules were the safety floor the whole time. The full
arc is in the session receipts.

## Snowflake services used

Warehouses Â· Stages + PUT/COPY Â· Streams Â· Serverless Tasks (chained DAG)
Â· Stored Procedures Â· VECTOR datatype + vector similarity functions Â·
Resource Monitors Â· Snowpark (Session + snowflake-ml) Â· Model Registry Â·
Image Repository Â· Compute Pools Â· Snowpark Container Services (public
endpoint) Â· Semantic Views Â· Cortex Agents (DDL) Â· Notebooks (managed
Python) Â· CoCo CLI (deployment agent + custom Agent Skills)

## Cortex on trial accounts â€” the gate, documented

`SNOWFLAKE.CORTEX.COMPLETE`, `EMBED_TEXT_768`, Cortex Search, Document AI
runtime, and `DATA_AGENT_RUN` return *"not available for trial accounts"*
on every account class this hackathon provides â€” verified on four
accounts including two created through dedicated hackathon links, with
query IDs on the support ticket. The model-role grant path
(`CORTEX-MODEL-ROLE-ALL`) was also tested: the gate sits above it.

ForgePulse therefore ships **Cortex-native definitions with local
adapters at runtime**: COMPLETE â†’ local mistral (narratives), EMBED â†’
bge-m3 into Snowflake VECTOR columns (retrieval still runs in Snowflake),
Document AI â†’ local qwen2.5-vl (validated 100%). Every adapter output is
tagged `local | cortex pending access`, and the semantic view + agent
exist as real objects (`sql/07_semantic_agent.sql`) so the day the gate
lifts, the swap is an env change, not a rebuild.

## CoCo CLI as the deployment agent

The entire system was deployed to this account **by CoCo in agentic
sessions** â€” schema, 1.24M-row load with verified counts, streams, procs,
task DAG, fault catalog, SPCS service. Receipts (prompts, approvals,
incidents, self-corrections â€” including CoCo detecting its own over-firing
delete against a known-good count and recovering by clean reload) are in
`docs/coco-sessions/`. Three custom **Agent Skills**
(`failure-prediction`, `rca-investigation`, `work-order-dispatch`) let
CoCo operate the plant conversationally; both investigation skills are
live-verified in the receipts.

## Repository map

```
sql/            01_schema â€¦ 07_semantic_agent â€” the account, reproducible
src/            generators, kafka pipe, workers, extraction, embedding,
                training, enrichment
forgepulse-ui/  FastAPI backend (Snowflake-backed + mock) + console +
                Dockerfile/spec for SPCS
scripts/        run.ps1 orchestrator (-Feed -Worker -Ui -All), env template
skills/         CoCo agent skills
tests/          18-test pytest suite (feature math, extraction validation,
                API contract, idempotency regression)
reports/        scanned corpus + ground truth + extracted fields
docs/           BRD, redeploy runbook, SPCS runbook, session receipts
```

## Run it

```powershell
# one-time: python -m venv .venv ; pip install -r requirements.txt
# copy scripts\env.example.ps1 -> scripts\env.ps1 and fill credentials
.\scripts\run.ps1 -All        # kafka + producer + consumer + workers + console
pytest                        # 18 tests
```

Full account redeploy from empty: `docs/redeploy.md` â€” rehearsed three
times, roughly one hour via a single CoCo prompt.

---

*Built solo by Mrinal Desai for the Snowflake CoCo CLI Hackathon 2026.*

