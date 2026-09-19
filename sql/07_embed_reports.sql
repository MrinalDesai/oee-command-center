-- 07_embed_reports.sql — Native Cortex embedding for the repair-report corpus.
-- Replaces the local bge-m3/Ollama path (src/embed_reports.py) with
-- SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', ...).
-- Fully qualified names throughout. Idempotent (CREATE OR REPLACE + MERGE).

-- ── Embeddings table (768-dim, matching snowflake-arctic-embed-m) ────────────
CREATE OR REPLACE TABLE OEE_DB.ANALYTICS.REPORT_EMBEDDINGS (
  report_id         VARCHAR(12) PRIMARY KEY,
  fault_pattern_id  VARCHAR(6),
  asset_id          VARCHAR(10),
  model_no          VARCHAR(30),
  content           VARCHAR(4000),
  embedding         VECTOR(FLOAT, 768),
  embedded_by       VARCHAR(60) DEFAULT 'snowflake-arctic-embed-m via CORTEX.EMBED_TEXT_768'
);

-- ── Embed all extracted reports ──────────────────────────────────────────────
INSERT INTO OEE_DB.ANALYTICS.REPORT_EMBEDDINGS
  (report_id, fault_pattern_id, asset_id, model_no, content, embedding)
SELECT
  r.report_id,
  r.fault_pattern_id,
  r.asset_id,
  r.model_no,
  'Asset ' || r.asset_id || ' model ' || r.model_no
    || ' pattern ' || r.fault_pattern_id || '. '
    || 'Symptoms: ' || r.symptoms
    || ' Diagnosis: ' || r.diagnosis
    || ' Parts: ' || COALESCE(r.parts_replaced, 'none') AS content,
  SNOWFLAKE.CORTEX.EMBED_TEXT_768(
    'snowflake-arctic-embed-m',
    'Asset ' || r.asset_id || ' model ' || r.model_no
      || ' pattern ' || r.fault_pattern_id || '. '
      || 'Symptoms: ' || r.symptoms
      || ' Diagnosis: ' || r.diagnosis
      || ' Parts: ' || COALESCE(r.parts_replaced, 'none')
  )
FROM OEE_DB.ANALYTICS.EXTRACTED_REPORTS r;

-- ── Verification: cosine similarity search ───────────────────────────────────
-- SELECT report_id, fault_pattern_id, asset_id,
--        VECTOR_COSINE_SIMILARITY(
--          embedding,
--          SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', 'bearing failure')
--        ) AS score,
--        LEFT(content, 120)
-- FROM OEE_DB.ANALYTICS.REPORT_EMBEDDINGS
-- ORDER BY score DESC
-- LIMIT 5;
