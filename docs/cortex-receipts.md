# Cortex Execution Receipts — YRCKWDT-CNB10903

Evidence that `SNOWFLAKE.CORTEX.COMPLETE` and `SNOWFLAKE.CORTEX.EMBED_TEXT_768`
execute successfully on the submission account, after the AI Data Cloud
entitlement lifted the trial gate documented in the README.

Account: **YRCKWDT-CNB10903** · AWS us-west-2 · Enterprise
Query IDs are verifiable in Snowsight → Monitoring → Query History.
Timestamps are account-local (America/Los_Angeles, UTC-7).

---

## 1. Entitlement verification

The two gate tests that had returned *"not available for trial accounts"* on
every previous account class.

| Function | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| `CORTEX.COMPLETE('llama3.1-70b', …)` | `01c72312-010b-8457-0032-db570005a01a` | SUCCESS | 2026-09-17 11:58:23 | 1 |
| `CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', …)` | `01c72312-010b-7b0f-0032-db5700050db2` | SUCCESS | 2026-09-17 11:58:28 | 1 |

`COMPLETE` returned `OK`. `EMBED_TEXT_768` returned a 768-element float vector.

---

## 2. RCA narrative generated in-procedure by CORTEX.COMPLETE

`DIAGNOSE_FINDINGS()` was redeployed with the `[PENDING_NARRATIVE]` stub
replaced by an inline `CORTEX.COMPLETE` call against the evidence dossier
(`sql/04_diagnose.sql`).

| Step | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| `CREATE OR REPLACE PROCEDURE …DIAGNOSE_FINDINGS()` | `01c72bc8-010b-8901-0032-db57000940d6` | SUCCESS | 2026-09-19 01:08:24 | — |
| `INSERT INTO …FINDINGS (… rca_summary …)` — narrative written | `01c72bc9-010b-8aae-0032-db5700093082` | SUCCESS | 2026-09-19 01:09:02 | 1 |

Resulting narrative for AST-007 (finding 101) cites the live feature values and
two real work orders from the plant's own history:

> The probable failure mode is bearing degradation, as indicated by the high
> vibration reading (vib_now: 10.64 mm/s) and increasing vibration slope
> (vib_slope_per_day: 1.76 mm/s/day). The temperature reading (temp_now: 79.8°C)
> and temperature slope (temp_slope_per_day: 1.992°C/day) also suggest an
> abnormal condition. This failure mode is consistent with historical work
> orders WO-24290 and WO-24101, which involved bearing failures on similar
> assets. The prognosis is that the compressor is at high risk of imminent
> failure, with a high likelihood of bearing seizure or other catastrophic
> failure if not addressed promptly.

---

## 3. Report corpus embedded natively at 768 dimensions

The twenty scanned repair reports were re-embedded from local bge-m3
(`VECTOR(FLOAT,1024)`) to Cortex (`VECTOR(FLOAT,768)`) — `sql/07_embed_reports.sql`.

| Step | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| `CREATE OR REPLACE TABLE …REPORT_EMBEDDINGS (… VECTOR(FLOAT,768))` | `01c72bd0-010b-87e4-0032-db570009609a` | SUCCESS | 2026-09-19 01:16:32 | — |
| `INSERT … SELECT CORTEX.EMBED_TEXT_768(…)` — **20 reports embedded** | `01c72bd1-010b-8971-0032-db570009209e` | SUCCESS | 2026-09-19 01:17:10 | **20** |

---

## 4. Semantic retrieval over the Cortex-embedded corpus

`VECTOR_COSINE_SIMILARITY` against the 768-dim corpus, query embedded in-account
by `EMBED_TEXT_768` — no local model in the path.

| Step | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| Similarity search, verification run | `01c72bd2-010b-8854-0032-db570008f0d2` | SUCCESS | 2026-09-19 01:18:25 | 3 |
| Similarity search from `enrich_worker.py` | `01c72c09-010b-8901-0032-db570009436e` | SUCCESS | 2026-09-19 02:13:00 | 3 |
| Console diagnosis panel retrieval | `01c72c62-010b-8971-0032-db570009243a` | SUCCESS | 2026-09-19 03:42:41 | 5 |

Top matches for the AST-007 symptom text, all FP-01 bearing reports:

| Report | Pattern | Asset | Score |
|---|---|---|---|
| RPT-4003 | FP-01 | AST-007 | 0.64 |
| RPT-4002 | FP-01 | AST-009 | 0.61 |
| RPT-4013 | FP-03 | AST-008 | 0.60 |

RPT-4003 is a prior bearing event on AST-007 itself — the asset the live
pipeline has just flagged.

---

## 5. Enrichment table populated

| Step | Query ID | Status | Time | Rows |
|---|---|---|---|---|
| `CREATE TABLE IF NOT EXISTS …FINDING_ENRICHMENT` | `01c72c08-010b-87e4-0032-db570009635e` | SUCCESS | 2026-09-19 02:12:56 | — |
| `UPDATE …FINDING_ENRICHMENT SET enriched_by = …` | `01c72c10-010b-8dd8-0032-db570009e2b2` | SUCCESS | 2026-09-19 02:20:56 | 1 |

`enriched_by` now records `xgboost registry-model + cortex EMBED_TEXT_768`,
replacing the adapter-era label.

---

## Summary

| Claim in README | Evidence |
|---|---|
| Cortex is entitled on the submission account | §1 — both gate functions SUCCESS |
| RCA narratives generated in-procedure by COMPLETE | §2 — procedure + narrative row |
| Corpus embedded by EMBED_TEXT_768 into VECTOR(FLOAT,768) | §3 — 20 rows embedded |
| Retrieval runs end to end inside the account | §4 — three successful similarity queries |
| No local model in the serving path | §2–4 — every step is a Snowflake query ID |
