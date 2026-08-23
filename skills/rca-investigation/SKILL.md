---
name: rca-investigation
description: Investigate the root cause of an asset fault - assembles the evidence dossier (live features, asset context, fleet repair history via semantic search) and explains the diagnosis with confidence and supporting records. Use when asked "why is X failing", "root cause", "what happened to asset X", or "show the evidence".
---

# Root-cause investigation

Explain WHY an asset is faulted, grounded entirely in retrievable evidence.

## Data sources
- `OEE_DB.ANALYTICS.FINDINGS` - the RCA narrative written by the diagnosis
  layer (structured Observed / Probable cause / History / Urgency)
- `OEE_DB.ANALYTICS.FINDING_ENRICHMENT` - classifier verdict, confidence,
  probabilities, SHAP top_factors, similar_reports (JSON)
- `OEE_DB.ANALYTICS.EXTRACTED_REPORTS` - fields extracted from scanned
  handwritten repair reports (vision-model pipeline, validated 100/100)
- `OEE_DB.ANALYTICS.REPORT_EMBEDDINGS` - bge-m3 vectors in
  `VECTOR(FLOAT,1024)`; retrieval via `VECTOR_COSINE_SIMILARITY` in SQL
- `OEE_DB.ERP.WORK_ORDER_HISTORY` - structured downtime history

## Procedure
1. Pull the latest finding + enrichment for the asset (LEFT JOIN - the
   enrichment may lag behind a fresh finding).
2. Present: verdict + confidence, the top factors WITH their live values,
   then the narrative's numbered sections.
3. Fleet history: list similar_reports (report id, asset, similarity %,
   remedy, parts, downtime). These come from semantic search over the
   scanned corpus - cite them as "similar past repairs", never as this
   asset's own history unless asset_id matches.
4. If asked to search history directly, embed the query text with the
   available embedding function and rank REPORT_EMBEDDINGS by cosine
   similarity in SQL - retrieval happens inside Snowflake.

## Rules
- Every claim must trace to a table row; quote report ids and WO ids.
- If the classifier and the rule layer disagree, show both and say which
  is authoritative (rules) and why the model differs.
- Distinguish same-asset history from same-model fleet history explicitly.
