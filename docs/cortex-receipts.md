# Cortex Execution Receipts — XSJWISO-MIB54927

Evidence that `SNOWFLAKE.CORTEX.COMPLETE` and `SNOWFLAKE.CORTEX.EMBED_TEXT_768`
execute successfully on the submission account, after the AI Data Cloud
entitlement lifted the trial gate documented in the README.

Account: **XSJWISO-MIB54927** · AWS us-west-2 · Enterprise
Query IDs are verifiable in Snowsight → Monitoring → Query History.
Timestamps are account-local (America/Los_Angeles, UTC-7).

---

## 1. Entitlement verification

The two gate tests that had returned *"not available for trial accounts"* on
every previous account class.

| Function | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| `CORTEX.COMPLETE('llama3.1-70b', …)` | `01c7546a-040b-a79a-0033-314f00073026` | SUCCESS | 2026-09-26 06:30:59 | 1 |
| `CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', …)` | `01c7546b-040b-ac8e-0033-314f00076fe6` | SUCCESS | 2026-09-26 06:31:12 | 1 |

`COMPLETE` returned `OK`. `EMBED_TEXT_768` returned a 768-element float vector.

---

## 2. RCA narrative generated in-procedure by CORTEX.COMPLETE

`DIAGNOSE_FINDINGS()` carries the `CORTEX.COMPLETE` call inline, against the
evidence dossier assembled from detection features and fleet work-order
history (`sql/04_diagnose.sql`).

| Step | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| `CREATE OR REPLACE PROCEDURE …DIAGNOSE_FINDINGS()` | `01c76366-040b-b950-0033-314f0008d02e` | SUCCESS | 2026-09-28 22:26:38 | — |
| `INSERT INTO …FINDINGS (… rca_summary …)` — narrative written | `01c7636c-040b-aee8-0033-314f000741ae` | SUCCESS | 2026-09-28 22:32:02 | 1 |

Resulting narrative for AST-007, citing the live feature values and two real
work orders from the plant's own history:

> The probable failure mode is bearing failure due to excessive vibration, as
> indicated by the high vibration reading (10.64 mm/s) and increasing vibration
> slope (+1.76 mm/s/day). The temperature reading (79.8°C) and temperature
> slope (+1.992°C/day) also suggest an abnormal operating condition. This
> failure mode is consistent with historical work orders WO-24290 and WO-24101,
> which involved bearing failures on similar assets. The prognosis is that the
> compressor is likely to fail imminently, given the rapid increase in
> vibration and temperature readings.

---

## 3. Report corpus embedded natively at 768 dimensions

The twenty scanned repair reports are embedded by Cortex into a
`VECTOR(FLOAT,768)` column — `sql/07_embed_reports.sql`.

| Step | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| `CREATE OR REPLACE TABLE …REPORT_EMBEDDINGS (… VECTOR(FLOAT,768))` | `01c76370-040b-a07c-0033-314f0006b136` | SUCCESS | 2026-09-28 22:36:54 | — |
| `INSERT … SELECT CORTEX.EMBED_TEXT_768(…)` — **20 reports embedded** | `01c76371-040b-9e4b-0033-314f0007123a` | SUCCESS | 2026-09-28 22:37:03 | **20** |

---

## 4. Semantic retrieval over the Cortex-embedded corpus

`VECTOR_COSINE_SIMILARITY` against the 768-dim corpus, query embedded
in-account by `EMBED_TEXT_768` — no local model in the path.

| Step | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| Similarity search, verification run | `01c76371-040b-ace9-0033-314f0007230e` | SUCCESS | 2026-09-28 22:37:17 | 3 |
| Similarity search from `enrich_worker.py` | `01c76373-040b-9feb-0033-314f0005f28a` | SUCCESS | 2026-09-28 22:39:59 | 3 |

Top matches for "bearing failure", all FP-01 bearing reports:

| Report | Pattern | Asset | Score |
|---|---|---|---|
| RPT-4002 | FP-01 | AST-009 | 0.581 |
| RPT-4003 | FP-01 | AST-007 | 0.575 |
| RPT-4001 | FP-01 | AST-003 | 0.554 |

RPT-4003 is a prior bearing event on AST-007 itself — the asset the live
pipeline has just flagged.

---

## 5. Enrichment table populated

| Step | Query ID | Status | Time |
|---|---|---|---|
| `CREATE TABLE IF NOT EXISTS …FINDING_ENRICHMENT` | `01c76373-040b-9feb-0033-314f0005f286` | SUCCESS | 2026-09-28 22:39:52 |

`enriched_by` records `xgboost registry-model + cortex EMBED_TEXT_768`.
The registered classifier returns FP-01 at 99% for the AST-007 window, served
natively via `FAULT_PATTERN_CLASSIFIER!PREDICT_PROBA`.

---

## Summary

| Claim in README | Evidence |
|---|---|
| Cortex is entitled on the submission account | §1 — both gate functions SUCCESS |
| RCA narratives generated in-procedure by COMPLETE | §2 — procedure + narrative row |
| Corpus embedded by EMBED_TEXT_768 into VECTOR(FLOAT,768) | §3 — 20 rows embedded |
| Retrieval runs end to end inside the account | §4 — two successful similarity queries |
| No local model in the serving path | §2–4 — every step is a Snowflake query ID |

---

*The pipeline was first brought up Cortex-native on the earlier build account
YRCKWDT-CNB10903 (19 Sep 2026); this document records the submission account.
Both run identical code from this repository.*
