# Cortex Execution Receipts — VQYUEYO-CGB78487

Evidence that `SNOWFLAKE.CORTEX.COMPLETE` and `SNOWFLAKE.CORTEX.EMBED_TEXT_768`
execute successfully on the submission account, after the AI Data Cloud
entitlement lifted the trial gate documented in the README.

Account: **VQYUEYO-CGB78487** · AWS us-west-2 · Enterprise
Query IDs are verifiable in Snowsight → Monitoring → Query History, and in
`SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`.
Timestamps are account-local (America/Los_Angeles, UTC-7).

---

## 1. Entitlement verification

The two gate tests that had returned *"not available for trial accounts"* on
every Cortex Code CLI account class.

| Function | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| `CORTEX.COMPLETE('llama3.1-70b', …)` | `01c77428-040b-b9a3-0033-6df700049026` | SUCCESS | 2026-10-01 21:56:19 | 1 |
| `CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', …)` | `01c77428-040b-c064-0033-6df700036a62` | SUCCESS | 2026-10-01 21:56:35 | 1 |

`COMPLETE` returned `OK`. `EMBED_TEXT_768` returned a 768-element float vector.

---

## 2. RCA narrative generated in-procedure by CORTEX.COMPLETE

`DIAGNOSE_FINDINGS()` carries the `CORTEX.COMPLETE` call inline, against an
evidence dossier assembled from detection features and fleet work-order history
(`sql/04_diagnose.sql`).

| Step | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| `CREATE OR REPLACE PROCEDURE …DIAGNOSE_FINDINGS()` | `01c7744f-040b-c05e-0033-6df700037032` | SUCCESS | 2026-10-01 22:35:37 | — |
| `INSERT INTO …FINDINGS (… rca_summary …)` — narrative written | `01c77454-040b-bebf-0033-6df700041092` | SUCCESS | 2026-10-01 22:40:42 | 1 |

Resulting narrative for AST-007, citing the live feature values and two real
work orders from the plant's own history:

> The probable failure mode is bearing failure, as indicated by the high
> vibration readings (vib_now: 10.64 mm/s, vib_z: 32.31) and increasing
> vibration slope (1.76 mm/s/day). The temperature readings also show a
> concerning trend (temp_now: 79.8 C, temp_slope: 1.99 C/day, temp_z: 10.19).
> These sensor readings are consistent with historical work orders WO-24290 and
> WO-24101, which also involved bearing failures on similar compressor assets.
> Given the criticality of the asset and the rapid progression of the fault, a
> bearing failure is likely imminent, if not already occurring.

---

## 3. Report corpus embedded natively at 768 dimensions

The twenty scanned repair reports are embedded by Cortex into a
`VECTOR(FLOAT, 768)` column — `sql/07_embed_reports.sql`.

| Step | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| `CREATE OR REPLACE TABLE …REPORT_EMBEDDINGS (… VECTOR(FLOAT,768))` | `01c77457-040b-d185-0033-6df70004b06a` | SUCCESS | 2026-10-01 22:43:35 | — |
| `INSERT … SELECT CORTEX.EMBED_TEXT_768(…)` — **20 reports embedded** | `01c77457-040b-bebf-0033-6df7000410a6` | SUCCESS | 2026-10-01 22:43:43 | **20** |

---

## 4. Semantic retrieval over the Cortex-embedded corpus

`VECTOR_COSINE_SIMILARITY` against the 768-dim corpus, query embedded
in-account by `EMBED_TEXT_768` — no local model in the path.

| Step | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| Similarity search, verification run | `01c77457-040b-d185-0033-6df70004b06e` | SUCCESS | 2026-10-01 22:43:53 | 3 |
| Similarity search from `enrich_worker.py` | `01c7745d-040b-c567-0033-6df700042092` | SUCCESS | 2026-10-01 22:49:03 | 3 |

Top matches for "bearing failure", all FP-01 bearing reports:

| Report | Pattern | Asset | Score |
|---|---|---|---|
| RPT-4002 | FP-01 | AST-009 | 0.5812 |
| RPT-4003 | FP-01 | AST-007 | 0.5750 |
| RPT-4001 | FP-01 | AST-003 | 0.5535 |

RPT-4003 is a prior bearing event on AST-007 itself — the asset the live
pipeline has just flagged.

---

## 5. Enrichment table populated

| Step | Query ID | Status | Time |
|---|---|---|---|
| `CREATE TABLE IF NOT EXISTS …FINDING_ENRICHMENT` | `01c7745c-040b-c78c-0033-6df70004605a` | SUCCESS | 2026-10-01 22:48:54 |

`enriched_by` records `xgboost registry-model + cortex EMBED_TEXT_768`.
The registered classifier returns FP-01 at 98.17% for the AST-007 window,
served natively via `FAULT_PATTERN_CLASSIFIER!PREDICT_PROBA` in warehouse SQL.

---

## Summary

| Claim in README | Evidence |
|---|---|
| Cortex is entitled on the submission account | §1 — both gate functions SUCCESS |
| RCA narratives generated in-procedure by COMPLETE | §2 — procedure + narrative row |
| Corpus embedded by EMBED_TEXT_768 into VECTOR(FLOAT, 768) | §3 — 20 rows embedded |
| Retrieval runs end to end inside the account | §4 — two successful similarity queries |
| No local model in the serving path | §2–4 — every step is a Snowflake query ID |

---

*The pipeline was brought up Cortex-native on three AI Data Cloud accounts in
sequence as the organizers issued successive credit links — YRCKWDT-CNB10903
(19 Sep), XSJWISO-MIB54927 (29 Sep) and this one (2 Oct). All three run
identical code from this repository, and the detection features, similarity
scores and classifier confidence are byte-identical across them because the
telemetry generator is seeded.*
