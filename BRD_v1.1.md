# Business Requirements Document
## OEE Command Center — Predictive Maintenance on Snowflake
**Snowflake CoCo CLI Hackathon 2026 · Track 3: Predictive Maintenance and OEE Command Center**
Version 1.1 · Owner: Mrinal Desai · Status: Approved for build
Changelog: v1.1 adds ML pattern classifier (trained on simulated failure corpus),
handwritten repair-report PDF corpus + OCR pipeline, days-to-threshold prediction,
bounded-autonomy action tiers. v1.0 baseline 2026-07-26.

---

## 1. Problem Statement

Manufacturers lose 5–20% of production capacity to unplanned downtime. The root cause is
structural: OT sensor data (vibration, temperature, RPM, current) lives in historians and
SCADA systems, while the context needed to act on it — maintenance history, spare parts,
production schedules, and above all the **paper trail of past repairs** — lives in ERP
systems and filing cabinets. Nobody joins them. Anomalies are visible in retrospect
("vib was trending up 10 days but alert missed") but not acted on in time, because
dashboards show insights and humans must notice, investigate, and raise work orders
manually.

**This system converges IT and OT data in Snowflake and closes the loop autonomously:**
detect the developing failure pattern in the live stream, predict what is failing and
when, investigate root cause against both structured records and scanned handwritten
repair reports, generate the work order with parts and schedule, notify the team — with
a human triaging by exception, not by vigilance.

## 2. Users and Personas

| Persona | Need | Primary surface |
|---|---|---|
| **Maintenance Planner** (primary) | 6 a.m. triage: what needs action today, in what order, with what parts | Alert queue + auto-generated work orders |
| **Reliability Engineer** | Investigate root cause; ask ad-hoc questions across telemetry, history, and old repair reports | Natural-language RCA (Cortex Agent) |
| **Plant / Ops Manager** | Is OEE improving? What did downtime cost? What was avoided? | OEE panel |

## 3. Business Impact (measurable)

- **Availability:** each caught failure avoids 6–12 h of unplanned downtime (per
  synthetic WO history). At 120 units/h line rate, one avoided AST-007-class failure
  ≈ **1,200+ units of protected output**.
- **Lead time:** prediction outputs estimated **days-to-threshold**, converting alarms
  from "it is failing" to "it fails Thursday — the PM window is Wednesday."
- **OEE:** availability losses dominate OEE detraction in the dataset; the demo
  quantifies **OEE points recovered** per avoided failure.
- **Labor:** investigation drops from hours of cross-system (and paper) archaeology to
  one NL question with cited evidence — including citations into scanned repair sheets.
- **The counterfactual is in the data:** WO-24290 (AST-009) documents a missed 10-day
  vibration trend that took a line down at night. The system demonstrably catches the
  identical developing pattern on AST-007, days in advance.

## 4. Scope

### In scope (submission)
1. Live streaming ingestion (Kafka → Snowflake) with autonomous detection pipeline
2. **ML failure-pattern classification** (registry-versioned model trained on a
   simulated labeled failure corpus) + physics-based days-to-threshold projection
3. **Handwritten repair-report corpus (synthetic scanned PDFs) → Cortex OCR/parse →
   structured extraction → Cortex Search index**
4. NL root-cause investigation grounded in structured + unstructured (scanned) evidence
5. Automated work-order generation with parts resolution, PM-window scheduling,
   notification — under bounded autonomy tiers
6. OEE computation from production schedule + downtime
7. Command-center UI (Streamlit in Snowflake), 3 screens
8. Three custom CoCo Agent Skills orchestrating the above
9. Governed semantic layer with verified queries + sql_correctness evaluation

### Out of scope (documented as production path only)
- Real OT connectivity (OpenFlow/MQTT at plant scale) — the Kafka path stands in;
  diagram-level note
- Live ERP integration (Snowflake Postgres) — Block 3 stretch
- SPCS 3D frontend — Block 3 stretch (**entitlement verified on trial, day 1**);
  Streamlit is the committed UI
- True Snowpipe Streaming sink (Kafka connector) — upgrade path from the working
  connector-insert sink; scheduled, not load-bearing

## 5. Data Assets

| Asset | Form | Role |
|---|---|---|
| Telemetry history | 1.24M rows, 90 days, 12 assets, 4 sensors, 5-min cadence | Baselines, training substrate, demo history |
| Live feed | Kafka topic `telemetry`, producer continues AST-007 ramp | Real-time detection substrate |
| Failure signatures | 5 historical episodes (3 bearing wear, 1 cooling, 1 sensor stuck-at) with full pre/during/post traces + 1 ACTIVE (AST-007) | Pattern library; demo hook |
| **Training corpus** | Generator `--training` mode: 200+ labeled episodes across modes, ramp rates (5–15 d), noise, load patterns | Classifier training (openly simulated — stated as methodology, standard practice where real failure data is scarce) |
| ERP records | Asset master, 41 WOs, parts inventory, production schedule | Correlation context, parts resolution, scheduling, OEE |
| **Handwritten repair reports** | ~15 synthetic scanned PDFs: failure time, symptoms, diagnosis, parts replaced, technician, serial no; handwriting font + rotation + scan noise; part numbers match inventory; 5 mirror the structured WOs | Unstructured evidence corpus; OCR pipeline input; RCA citations |

## 6. Functional Requirements

### FR-1 Detect & Predict (Skill: `failure-prediction`)
- FR-1.1 Feature engineering per asset over sliding 24 h / 72 h windows against 28-day
  baselines (median + MAD): vibration slope and acceleration, z-scores, variance,
  **vibration–temperature lag correlation**, RPM/current stability (~15 features)
- FR-1.2 **Classifier:** XGBoost over feature windows → P(BEARING_WEAR),
  P(COOLING_DEGRADATION), P(SENSOR_FAULT), P(NORMAL). Trained in Snowflake Notebook
  on the simulated corpus; logged to **Model Registry** as
  `FAILURE_PATTERN_CLASSIFIER v1`; invoked from the pipeline
- FR-1.3 **Stuck-at rule retained under the model** (near-zero variance ⇒ SENSOR_FAULT):
  rules own safety, model owns nuance — deterministic floor beneath probabilistic
  classification
- FR-1.4 **Days-to-threshold projection:** degradation slope extrapolated to alarm
  threshold ⇒ estimated lead time, reported with the classification
- FR-1.5 Autonomous: Kafka → RAW_TELEMETRY → append-only Stream (**built and verified
  day 1**) → serverless Task (`WHEN SYSTEM$STREAM_HAS_DATA`) → detection proc
- FR-1.6 Severity = f(P(mode), lead time, asset criticality); rows to
  `ANALYTICS.ANOMALY_EVENTS` (status NEW), idempotent
- FR-1.7 Every prediction decomposes to its features in evidence ("vib slope 0.4/day,
  temp lag 1 d, matches bearing profile 0.91") — no unexplained scores

### FR-2 Diagnose (Skill: `rca-investigation`)
- FR-2.1 For an event: telemetry stats, matching WO history, **matching scanned repair
  reports via Cortex Search over OCR-extracted text**, asset MTBF for the mode,
  install/PM dates
- FR-2.2 Cortex COMPLETE writes the finding: probable mode, confidence, lead time,
  evidence, recommended action
- FR-2.3 **Evidence-backed:** `FINDINGS.evidence_json` cites telemetry features, WO IDs,
  and repair-report serial numbers; no uncited claims
- FR-2.4 Decision branch: SENSOR_FAULT routes to data-quality queue — never a
  maintenance dispatch

### FR-3 Act (Skill: `work-order-dispatch`) — bounded autonomy tiers
- FR-3.1 **Tier A (HIGH severity, confident, non-sensor):** auto-create work order —
  priority, Cortex-written description, parts resolved against inventory with
  stock/lead-time check, **scheduled into the next PM window from
  PRODUCTION_SCHEDULE** — and fire Snowflake Alert/notification
- FR-3.2 **Tier B (MEDIUM):** scheduled work order created, awaits one-click approval
  in UI
- FR-3.3 **Tier C (SENSOR_FAULT):** data-quality ticket; no parts ordered, ever
- FR-3.4 All actions logged; status machine NEW → INVESTIGATING → ACTIONED/DISMISSED,
  human-operable from UI. Autonomy is bounded and auditable by design.

### FR-4 Document Intelligence (pipeline, feeds FR-2)
- FR-4.1 PDFs staged → `AI_PARSE_DOCUMENT` extraction → structured table
  (report serial no, asset, failure ts, symptoms, diagnosis, parts) → full text into
  **Cortex Search** service (native vector indexing — no external vector store)
- FR-4.2 Pipeline built via `document-intelligence` / `ai-functions-pipeline-builder`
  CoCo skills; incremental (new PDF ⇒ stream → task → parse → index)
- FR-4.3 Extraction quality spot-checked; extraction confidence stored

### FR-5 Ask (Cortex Agent + semantic view)
- FR-5.1 NL over structured data via Cortex Analyst on semantic view (canonical
  metrics: MTBF, OEE, availability, downtime hours)
- FR-5.2 NL over unstructured via Cortex Search (repair reports, technician notes)
- FR-5.3 Seeded verified queries; native Analyst Evaluation run; sql_correctness
  score reported in README

### FR-6 OEE
- FR-6.1 OEE = Availability × Performance × Quality from PRODUCTION_SCHEDULE
- FR-6.2 Per line, per day/shift; trend view; downtime-avoided → OEE-points-recovered
  for actioned findings

## 7. Architecture

```
                              ┌───────────────────────── SNOWFLAKE ─────────────────────────┐
 Kafka (live feed) ──► sink ─► OT.RAW_TELEMETRY ─► Stream ─► Task ──────────┐               │
 [prod: OpenFlow /            (upgrade: Snowpipe Streaming)                 ▼               │
  Kafka connector]                                     feature eng (Dynamic Tables) ─►      │
 ERP CSVs ───────────► Stage/COPY ─► ERP.*             detection proc + Registry model      │
 [prod: SF Postgres]                                   + slope projection (days-to-thresh)  │
                                                                    │                       │
 Scanned repair PDFs ─► Stage ─► AI_PARSE_DOCUMENT ─► extracted     ▼                       │
                                  table + Cortex      ANALYTICS.ANOMALY_EVENTS              │
                                  Search index ◄──┐                 │                       │
                                                  │                 ▼                       │
                     Cortex Analyst (semantic view)┴─ Cortex Agent (RCA) ─► FINDINGS        │
                                                                    │      (evidence_json   │
                                                                    ▼       cites reports)  │
                                            WORK_ORDERS_GENERATED (autonomy tiers A/B/C)    │
                                                     + Alert/Notify                         │
                                                                    │                       │
                                  Streamlit in Snowflake ◄──────────┘                       │
                                  (command center, 3 screens)                               │
                              └─────────────────────────────────────────────────────────────┘
 Built and orchestrated end-to-end via CoCo CLI: AGENTS.md + 3 custom Agent Skills
 ML lifecycle: Snowflake Notebook ─► Model Registry (versioned) ─► pipeline inference
```

## 8. UI / Web Design Specification

**Register:** mission-control / NOC console. Dark, information-dense, calm until
something isn't. No decoration that doesn't carry information. The user is a planner at
6 a.m. with coffee — clarity beats cleverness.

### 8.1 Design tokens
- **Background:** `#0B0F14` · panels `#111823` · borders `#1E2A38`
- **Text:** primary `#E6EDF3`, secondary `#8B98A5`
- **Status (the only saturated colors):** healthy `#2EA043` · watch `#D29922` ·
  critical `#F85149` · sensor-fault `#8957E5`
- **Accent (interactive):** `#388BFD`
- **Type:** Inter/system sans; values in JetBrains Mono. 13px body, 11px uppercase
  labels (+0.5px tracking), 20px KPI numbers
- **Spacing:** 8px grid · cards radius 8px · 1px borders, no shadows

### 8.2 Screens (3, no more)

**S1 — Plant Overview (default).** KPI strip (Plant OEE + 7-day sparkline,
Availability, Performance, Quality, Open Alerts, Active WOs). Asset health grid —
12 cards (3 lines × 4): status color, name, worst-sensor 24 h sparkline, health score,
**predicted lead time on degrading assets ("~4 d")**. Critical cards pulse subtly
(2 s, opacity 0.85↔1.0 — the app's only animation). Click → S2 filtered.

**S2 — Alert Triage & Investigation.** Left 40%: queue sorted severity × criticality —
status chip, asset, type, P(mode), lead time, detected-at; Investigate / Dismiss.
Right 60%: telemetry chart with baseline band + anomaly window; **RCA finding card** —
mode, confidence, lead time, evidence chips (feature values, WO IDs, **repair-report
serials — clicking a report chip shows the scanned page beside its extracted text**);
work-order preview (parts + stock status + proposed PM slot), Approve/Edit.
**NL bar pinned bottom** → Cortex Agent, answers cite sources. Sensor-fault alerts
render purple with "Data Quality" badge — the decision branch, visible.

**S3 — OEE & History.** OEE waterfall per line; trend chart with WO markers annotating
dips; "value protected" card (downtime avoided × line rate for actioned predictive WOs);
filterable work-order table (generated + historical).

### 8.3 Interaction rules
- Every AI statement displays its evidence; every prediction its features
- No dead ends: every alert reaches Actioned or Dismissed
- Empty states designed ("No critical alerts — plant nominal")
- Auto-refresh 60 s on S1/S2; visible manual refresh

### 8.4 Block 3 stretch (register unchanged)
React + Three.js on SPCS (**entitlement verified**): isometric 3-line plant floor,
assets as glowing units in the same palette, click-through to the S2 flow. Additive,
never load-bearing; Streamlit remains the committed UI.

## 9. Non-Functional Requirements
- **Reproducibility:** full deploy from repo (`docs/redeploy.md`); fresh account →
  running demo < 1 h; generator is seeded/deterministic — the data is code
- **Cost:** XS warehouses, 60 s auto-suspend, serverless Tasks, resource monitors
  (CARD_GUARD pattern), query tags; cost design in README
- **Governance:** RBAC roles (ENGINEER / ANALYST / AGENT), semantic view as governed
  NL layer, autonomy tiers auditable, no credentials in code or chat
- **Code quality:** ruff-clean, typed, pytest, CI on push — repo is statically
  analyzed by judges; treat as scored surface
- **Honesty of method:** simulated training corpus disclosed as such; no claims the
  data can't support

## 10. Acceptance Criteria (demo = proof)
1. Kafka feed live → Task fires unprompted → AST-007 in ANOMALY_EVENTS as HIGH with
   **P(BEARING_WEAR) and days-to-threshold** within one cycle
2. RCA finding cites WO-24290's note ("this was avoidable"), a **scanned repair
   report by serial number**, and MTBF context; evidence_json fully populated
3. Tier A work order auto-created: correct bearing part class, stock checked,
   **scheduled into an actual PM window**; notification fires
4. Stuck-at sensor classified SENSOR_FAULT, routed purple to data quality — no parts
   ordered
5. NL: "which assets are trending toward failure and what will it cost us?" →
   governed, cited answer spanning structured + scanned sources
6. OEE panel shows availability impact and value protected
7. Repair-report chip click renders the scanned page beside extracted fields —
   OCR pipeline visible end to end
8. All executed through the CLI-built pipeline in one uninterrupted take

## 11. Milestones
- **G1 (Jul 29):** spine end-to-end with rule-based scoring — Stream (✓ day 1) →
  Task → detect → finding → work order → notify; ugly allowed
- **G1.5 (Jul 30–31):** PDF corpus + OCR pipeline + Search index; RCA cites documents
- **G2 (Aug 2–3):** ML layer — training corpus, notebook, registry, classifier in
  pipeline, days-to-threshold; semantic view + verified queries + evaluation;
  tests green
- **G3 (Aug 4–6):** Streamlit UI (3 screens), scripted demo, video draft,
  submission-ready state
- **Aug 7–23:** frozen (parallel hardware project) — maintenance only
- **G4 (Aug 24–30):** fresh-account redeploy (rehearsed), stretch (SPCS 3D, Postgres,
  Iceberg, Snowpipe Streaming sink), final video, **submit Aug 30**

## 12. Risks
| Risk | Mitigation |
|---|---|
| CoCo inference budget (~13 credits; 0.84 used day 1) exhausted | Batched prompts; generic dev outside CLI; $20 fallback accepted |
| Trial accounts expire ~Aug 25 | G4 opens with rehearsed redeploy; data-as-code |
| Classifier credibility challenged | Simulated corpus disclosed as methodology; rules floor beneath model; features interpretable |
| OCR extraction quality on handwriting | Font/noise tuned to AI_PARSE_DOCUMENT capability; extraction confidence stored; 5 reports mirror structured WOs as ground truth |
| Scope inflation (named pattern) | Gate system; G1 spine before G1.5 documents before G2 ML; nothing merges half-working |
| Preview-feature gaps | Day-1 verified: agents, search, analyst, streamlit, SPCS ✓ |
| Organizer timeline/theme drift | Weekly dashboard check (public page already went stale once) |
