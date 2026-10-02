<div align="center">

<img src="docs/images/forgepulse-logo.png" alt="ForgePulse" width="420">

### Predictive Maintenance & OEE Command Center

**Snowflake CoCo CLI Hackathon 2026 · GCC Edition**
Team **SoloNomad** · Mrinal Prakash Desai · Team size 1

[![Live console](https://img.shields.io/badge/Live_console-open-29B5E8?style=for-the-badge&logo=snowflake&logoColor=white)](https://eq3xntb-vqyueyo-cgb78487.snowflakecomputing.app)
[![Demo video](https://img.shields.io/badge/Demo_video-watch-FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://www.youtube.com/watch?v=BwjjUCThBgw)

![Cortex](https://img.shields.io/badge/Cortex-COMPLETE%20%2B%20EMBED__TEXT__768-29B5E8)
![Model Registry](https://img.shields.io/badge/Model_Registry-XGBoost%20served%20in%20SQL-29B5E8)
![SPCS](https://img.shields.io/badge/SPCS-public%20endpoint-29B5E8)
![Rows](https://img.shields.io/badge/telemetry-1%2C244%2C160%20rows-2EA043)
![Tests](https://img.shields.io/badge/tests-18%2F18%20passing-2EA043)
![Extraction](https://img.shields.io/badge/document%20fields-100%2F100%20validated-2EA043)

</div>

---

A factory's machines stream sensor data into Snowflake. ForgePulse watches that
stream autonomously: it **detects** developing faults days before failure,
**investigates** the root cause against the plant's own repair history —
including scanned handwritten reports — **creates** the work order with parts and
a production-aware schedule, and **shows** a supervisor everything on a live
deployed console, with the projected OEE impact of acting early.

![AI Diagnosis panel](docs/images/02-ai-diagnosis.png)

---

## Access

> [!IMPORTANT]
> **Snowpark Container Services requires a Snowflake login on every endpoint**, so
> the console cannot be opened anonymously. A read-only account is provisioned on
> both deployments so the live system can be used, not just watched.
>
> | | |
> |---|---|
> | **Username** | `hackathon_judge` |
> | **Password** | `ForgePulse2026!Judge` |
>
> Every panel works with this login — plant floor, AI Diagnosis, Anomaly Lab,
> Repair History, OEE bridge, fault pipeline.

| | Link | Account | Live until |
|---|---|---|---|
| **Primary** | [eq3xntb-vqyueyo-cgb78487](https://eq3xntb-vqyueyo-cgb78487.snowflakecomputing.app) | `VQYUEYO-CGB78487` | ~1 Nov 2026 |
| **Mirror** | [eqhfgtb-xsjwiso-mib54927](https://eqhfgtb-xsjwiso-mib54927.snowflakecomputing.app) | `XSJWISO-MIB54927` | ~26 Oct 2026 |
| **Video** | [youtube.com/watch?v=BwjjUCThBgw](https://www.youtube.com/watch?v=BwjjUCThBgw) | — | — |

> [!NOTE]
> First load takes **2–3 minutes** while the SPCS compute pool resumes from idle.
> Both run on 30-day hackathon trial accounts. The system is fully reproducible
> from this repo — `docs/redeploy.md` plus `sql/08_load.sql` bring an empty
> account to a running console in about an hour. Happy to redeploy on request.

<details>
<summary><b>Verify the claims yourself</b> — the same login works in Snowsight</summary>

```sql
SELECT COUNT(*) FROM OEE_DB.OT.RAW_TELEMETRY;              -- 1,244,160
SELECT * FROM OEE_DB.ANALYTICS.ANOMALY_EVENTS;             -- AST-007, FP-01, HIGH
SELECT rca_summary FROM OEE_DB.ANALYTICS.FINDINGS;         -- Cortex COMPLETE narrative
SELECT COUNT(*) FROM OEE_DB.ANALYTICS.REPORT_EMBEDDINGS;   -- 20 x VECTOR(FLOAT, 768)
```

</details>

---

## The doctrine

> ### Rules own safety. Retrieval owns grounding. The model owns reasoning.

| Layer | Owns | In practice |
|---|---|---|
| **Deterministic rules** | Safety | Decide what is a fault, what severity, what tier of action. No model overrides the stuck-sensor floor or dispatches parts for an instrumentation error. |
| **Retrieval** | Grounding | The RCA narrative may only cite numbers that exist in query results. Fleet history comes from actual work orders and actual scanned repair reports found by semantic search. |
| **Models** | Reasoning | A registered XGBoost classifier adds pattern probability and explainable factors. Cortex COMPLETE writes the narrative from the evidence dossier. A vision model reads the scanned paperwork. |

---

## Architecture

![Architecture](docs/images/architecture.png)

### What happens, end to end

| # | Stage | What runs |
|---|---|---|
| **1** | **Stream** | A Kafka producer emits 4 sensors × 12 assets every 5 s; a consumer lands batches in `OT.RAW_TELEMETRY`. A Snowflake **stream** marks the new rows. |
| **2** | **Detect** <br>*autonomous* | A serverless **task** fires every minute but only spends compute when the stream has data. The **procedure** computes engineered features — z-scores against each asset's own 28-day baseline, slopes, variance collapse, vibration→temperature lag correlation — and opens an `ANOMALY_EVENTS` row with a fault-pattern ID. **Idempotency:** one open event per asset+mode; an ACTIONED event blocks re-alerting. |
| **3** | **Diagnose** <br>*autonomous* | The next task assembles the evidence dossier and writes a finding. `CORTEX.COMPLETE` turns the dossier into a structured narrative **inside the stored procedure**: Observed → Probable cause → Supporting history → Urgency. Every number traces to a table row. |
| **4** | **Enrich** <br>*explainability* | A worker computes the training-time features, runs the **Model Registry** classifier, extracts SHAP top factors, and retrieves the most similar past repairs by **VECTOR cosine similarity — inside Snowflake**. |
| **5** | **Act** <br>*autonomous* | Tier rules create the work order: parts checked against `SPARE_PARTS_INVENTORY`, repair scheduled into the lowest-load window in `PRODUCTION_SCHEDULE`, notification logged. **Sensor faults never dispatch parts.** |
| **6** | **Show** | The deployed console renders it all. |

![Fault pipeline](docs/images/05-fault-pipeline.png)

---

## The console

Twelve assets across three lines. Healthy is green; the machine in trouble is
not. Select it and everything the system knows is on one screen.

![Plant floor](docs/images/01-plant-floor.png)

The live monitor drives its display envelope from real values against real
baselines — **AST-007 sits at 11.95 mm/s RMS against a 3.41 mm/s baseline.**

![Live monitor](docs/images/01-live-monitor.png)

> [!TIP]
> **On alerts.** Active alerts are a sticky ticker pinned to the bottom of the
> viewport, visible at every scroll position — the NOC pattern from BRD §8: calm
> until something isn't. The sidebar *Alerts* entry anchors to that section;
> because the ticker is always on screen, that link is intentionally a no-op jump
> rather than a navigation.

### Anomaly Lab — inject and detect

A controlled synthetic signature, generated with the same feature assumptions as
the training pipeline, with one fault injected into a known segment. The
registered classifier runs over 18-hour sliding windows; the ground-truth bracket
is drawn underneath so the call can be **checked against the truth rather than
taken on trust**.

![Anomaly Lab](docs/images/03-anomaly-lab.png)

> Several overlapping windows fire on one injection, and they do not all agree.
> That is the real behaviour of a sliding-window classifier and it is shown as-is
> — the verdict line reports every window's call, not just the flattering one.

### The document layer

Twenty scanned, handwritten repair reports — generated with jitter, rotation and
scan noise; ground truth in `reports/reports_index.csv` — are read by a vision
model and validated field by field: **100/100 key fields correct.**

Each report is embedded by `CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', …)`
into a `VECTOR(FLOAT, 768)` column and searched with `VECTOR_COSINE_SIMILARITY`
in plain SQL. Fleet learning made visible: **a new fault on one machine cites its
siblings' repair paperwork.**

![Repair history library](docs/images/04-repair-history.png)

---

## CoCo CLI as the deployment agent

The entire system was deployed **by CoCo in agentic sessions** — schema, the
1.24 M-row load with verified counts, streams, procedures, task DAG, fault
catalog, Cortex-native diagnosis, model registration, SPCS service.

![CoCo redeploy](docs/images/09-coco-deploy.png)

Three custom **Agent Skills** let the engineering team interrogate and verify the
deployed workflow.

<details open>
<summary><b><code>$rca-investigation</code></b> — reasons across detection features, the Cortex narrative and the scanned corpus</summary>

<br>

It finds a prior bearing event on the same compressor from 18 months ago, dismisses
an unrelated cooling event, and dates the onset from the last preventive work order.

![rca-investigation](docs/images/06-coco-rca.png)

</details>

<details>
<summary><b><code>$failure-prediction</code></b> — scores all twelve assets through the Model Registry</summary>

<br>

It separates what is actionable from what is noise, and says plainly where the
model's decision boundary is unreliable rather than dressing it up.

![failure-prediction](docs/images/07-coco-failure-prediction.png)

</details>

<details>
<summary><b><code>$work-order-dispatch</code></b> — asked to raise a duplicate, it refused</summary>

<br>

It declined, citing the idempotency rule by name, and returned the existing order
with its full dispatch rationale. **A skill refusing to act because a rule forbids
it is the doctrine working, not a failure.**

![work-order-dispatch](docs/images/08-coco-work-order-dispatch.png)

</details>

Session receipts — prompts, approvals, incidents and self-corrections, including
CoCo detecting its own over-firing delete against a known-good count and
recovering by clean reload — are in [`docs/coco-sessions/`](docs/coco-sessions/).

---

## The classifier — an honest MLOps story

> [!WARNING]
> The classifier **initially misfired in serving**: 99 % confident of belt slip on
> a textbook bearing fault.

Eight documented iterations followed — feature train/serve skew, RPM regime
mixture from production-schedule speed changes, distribution shift from saturated
faults the training sim never contained, severity miscalibration — each diagnosed
with evidence (per-class feature means vs live values) and fixed at the root.

**Final state:** serving features computed with the exact training formulas; RPM
features excluded as a documented data-regime limitation, so FP-04 detection
remains rule-layer; the model agrees with the rule layer at **98.9 %** on AST-007,
served natively via `FAULT_PATTERN_CLASSIFIER!PREDICT_PROBA` with no Python at
inference time.

The rules were the safety floor the whole time.

---

## Snowflake services used

| Area | Services |
|---|---|
| **AI & ML** | Cortex AISQL (`COMPLETE`, `EMBED_TEXT_768`) · VECTOR datatype + similarity functions · Model Registry · Semantic Views · Cortex Agents |
| **Pipeline & data** | Streams · Serverless Tasks (chained DAG) · Stored Procedures · Stages + PUT/COPY · Warehouses · Resource Monitors · Snowpark (Session + snowflake-ml) |
| **Application** | Snowpark Container Services (public endpoint) · Image Repository · Compute Pools · Notebooks (managed Python) |
| **Agentic** | CoCo CLI as deployment agent · three custom Agent Skills |

---

## Cortex — gated for a month, native at the end

<details>
<summary><b>The full story</b></summary>

<br>

`CORTEX.COMPLETE`, `EMBED_TEXT_768`, Cortex Search, Document AI runtime and
`DATA_AGENT_RUN` returned *"not available for trial accounts"* on every account
class this hackathon provided for most of the build — verified across four
accounts including two created through dedicated hackathon links, with query IDs
on the support ticket. The model-role grant path (`CORTEX-MODEL-ROLE-ALL`) was
also tested: the gate sat above it.

ForgePulse was therefore architected as **Cortex-native definitions with local
adapters at runtime**, and shipped that way for six weeks.

The organizers' AI Data Cloud flow lifted the gate in the final week. The
submission account now runs **Cortex natively**: RCA narratives generated
in-procedure by `CORTEX.COMPLETE('llama3.1-70b', …)` against the evidence dossier,
and the twenty-report corpus embedded by `CORTEX.EMBED_TEXT_768` into
`VECTOR(FLOAT, 768)` and searched with `VECTOR_COSINE_SIMILARITY` — retrieval end
to end inside the account, no local model in the loop.

The adapters remain in the repo as the documented fallback (`src/llm_worker.py`,
`src/embed_reports.py`) for any account where the gate still applies, and document
extraction still runs through local qwen2.5-vl (validated 100 %).

**Built honest under constraint; swapped to native the day the door opened.**

</details>

📋 Execution evidence with Snowflake query IDs: [`docs/cortex-receipts.md`](docs/cortex-receipts.md)

---

## Repository map

```
sql/            01_schema … 08_load — the account, reproducible
src/            generators, kafka pipe, workers, extraction, embedding,
                training, enrichment
forgepulse-ui/  FastAPI backend (Snowflake-backed + mock) + console +
                Dockerfile/spec for SPCS
scripts/        run.ps1 orchestrator (-Feed -Worker -Ui -All), env template,
                deploy.py (SQL runner + stage/verify, CoCo-free path),
                register_classifier.py, fleet_predict.py
skills/         CoCo agent skills
tests/          18-test pytest suite (feature math, extraction validation,
                API contract, idempotency regression)
reports/        scanned corpus + ground truth + extracted fields
docs/           BRD, redeploy runbook, SPCS runbook, Cortex receipts,
                session receipts, screenshots
```

## Run it

```powershell
# one-time: python -m venv .venv ; pip install -r requirements.txt
# copy scripts\env.example.ps1 -> scripts\env.ps1 and fill credentials
.\scripts\run.ps1 -All        # kafka + producer + consumer + workers + console
pytest                        # 18 tests, green on a clean clone
```

Full account redeploy from empty: [`docs/redeploy.md`](docs/redeploy.md) —
rehearsed four times, roughly one hour via a single CoCo prompt, or via
`scripts/deploy.py` where the CoCo CLI is unavailable.

---

<div align="center">

**Built solo by Mrinal Prakash Desai**
Snowflake CoCo CLI Hackathon 2026 · GCC Edition

</div>
