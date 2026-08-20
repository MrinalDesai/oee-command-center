-- 03_detection.sql — OEE Command Center detection layer (G1 spine, rule-based)
-- Doctrine: rules own safety. The ML classifier (G2) will sit ON TOP of this,
-- never replacing the deterministic floor (stuck-at rule, tier gates).

USE DATABASE OEE_DB;

-- ── Schema upgrades ─────────────────────────────────────────────────────────

ALTER TABLE ANALYTICS.ANOMALY_EVENTS ADD COLUMN IF NOT EXISTS
  probable_mode      VARCHAR(30);          -- BEARING_WEAR | COOLING_DEGRADATION | SENSOR_FAULT
ALTER TABLE ANALYTICS.ANOMALY_EVENTS ADD COLUMN IF NOT EXISTS
  days_to_threshold  FLOAT;                -- NULL if not projectable
ALTER TABLE ANALYTICS.ANOMALY_EVENTS ADD COLUMN IF NOT EXISTS
  feature_json       VARIANT;             -- evidence: the numbers behind the flag

-- Notification audit: "notification fired" must be verifiable in data
CREATE TABLE IF NOT EXISTS ANALYTICS.NOTIFICATIONS_LOG (
  notification_id  NUMBER IDENTITY,
  event_id         NUMBER,
  channel          VARCHAR(30),            -- ALERT | EMAIL | UI
  recipient        VARCHAR(100),
  payload          VARCHAR(4000),
  sent_ts          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- ── Detection procedure ─────────────────────────────────────────────────────
-- Peeks at TELEMETRY_STREAM without consuming, runs detection against
-- RAW_TELEMETRY, then consumes the stream LAST (only on success).
-- Failure leaves the stream unconsumed for retry. Idempotent: one open
-- event per (asset, mode).

CREATE OR REPLACE PROCEDURE ANALYTICS.DETECT_ANOMALIES()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
  new_rows INTEGER DEFAULT 0;
  inserted INTEGER DEFAULT 0;
BEGIN

  -- 1) Non-consuming check: peek at the stream without advancing it.
  SELECT COUNT(*) INTO :new_rows FROM OT.TELEMETRY_STREAM;

  IF (new_rows = 0) THEN
    RETURN 'No new telemetry; nothing to do.';
  END IF;

  -- 2) Feature computation per asset over RAW_TELEMETRY (history + new rows).
  --    Baseline window: 28d ending 3d ago (excludes any active excursion).
  --    Recent window: last 24h. Slope window: last 72h (per-day units).
  CREATE OR REPLACE TEMPORARY TABLE _FEATURES AS
  WITH bounds AS (
    SELECT MAX(ts) AS now_ts FROM OT.RAW_TELEMETRY
  ),
  baseline_med AS (
    SELECT r.asset_id, r.sensor_type,
           MEDIAN(r.value) AS base_med
    FROM OT.RAW_TELEMETRY r, bounds b
    WHERE r.ts BETWEEN DATEADD(day,-31,b.now_ts) AND DATEADD(day,-3,b.now_ts)
      AND r.quality_flag = 'GOOD'
    GROUP BY r.asset_id, r.sensor_type
  ),
  baseline_deviations AS (
    SELECT r.asset_id, r.sensor_type,
           ABS(r.value - bm.base_med) AS abs_dev
    FROM OT.RAW_TELEMETRY r
    JOIN bounds b ON 1=1
    JOIN baseline_med bm ON bm.asset_id = r.asset_id AND bm.sensor_type = r.sensor_type
    WHERE r.ts BETWEEN DATEADD(day,-31,b.now_ts) AND DATEADD(day,-3,b.now_ts)
      AND r.quality_flag = 'GOOD'
  ),
  baseline AS (
    SELECT bd.asset_id, bd.sensor_type,
           bm.base_med,
           MEDIAN(bd.abs_dev) AS base_mad
    FROM baseline_deviations bd
    JOIN baseline_med bm ON bm.asset_id = bd.asset_id AND bm.sensor_type = bd.sensor_type
    GROUP BY bd.asset_id, bd.sensor_type, bm.base_med
  ),
  recent AS (
    SELECT r.asset_id, r.sensor_type,
           AVG(r.value)     AS recent_avg,
           STDDEV(r.value)  AS recent_std,
           COUNT(*)         AS n_recent
    FROM OT.RAW_TELEMETRY r, bounds b
    WHERE r.ts > DATEADD(hour,-24,b.now_ts)
    GROUP BY r.asset_id, r.sensor_type
  ),
  slope AS (
    SELECT r.asset_id, r.sensor_type,
           REGR_SLOPE(r.value,
                      DATEDIFF(second,'1970-01-01',r.ts)/86400.0) AS slope_per_day
    FROM OT.RAW_TELEMETRY r, bounds b
    WHERE r.ts > DATEADD(hour,-72,b.now_ts)
    GROUP BY r.asset_id, r.sensor_type
  )
  SELECT bl.asset_id, bl.sensor_type,
         bl.base_med, GREATEST(bl.base_mad, 0.001) AS base_mad,
         rc.recent_avg, rc.recent_std, rc.n_recent,
         s.slope_per_day,
         (rc.recent_avg - bl.base_med) / GREATEST(bl.base_mad,0.001) AS z_recent
  FROM baseline bl
  JOIN recent  rc ON rc.asset_id=bl.asset_id AND rc.sensor_type=bl.sensor_type
  JOIN slope   s  ON s.asset_id=bl.asset_id  AND s.sensor_type=bl.sensor_type;

  -- 3) Classify per asset. Rules, in priority order:
  --    SENSOR_FAULT: vibration variance ~0 over recent window (stuck-at).
  --    BEARING_WEAR: vibration z high AND rising AND temp also elevated/rising.
  --    COOLING_DEGRADATION: temp z high/rising while vibration normal.
  CREATE OR REPLACE TEMPORARY TABLE _VERDICTS AS
  WITH v AS (SELECT * FROM _FEATURES WHERE sensor_type='VIBRATION_RMS'),
       t AS (SELECT * FROM _FEATURES WHERE sensor_type='BEARING_TEMP')
  SELECT
    v.asset_id,
    CASE
      WHEN v.recent_std < 0.02 AND v.n_recent > 50               THEN 'SENSOR_FAULT'
      WHEN v.z_recent > 6 AND v.slope_per_day > 0.05
           AND (t.z_recent > 3 OR t.slope_per_day > 0.3)         THEN 'BEARING_WEAR'
      WHEN t.z_recent > 6 AND t.slope_per_day > 0.3
           AND v.z_recent < 3                                    THEN 'COOLING_DEGRADATION'
      ELSE NULL
    END AS probable_mode,
    v.z_recent      AS vib_z,
    v.slope_per_day AS vib_slope,
    v.recent_avg    AS vib_now,
    v.base_med      AS vib_base,
    v.recent_std    AS vib_std,
    t.z_recent      AS temp_z,
    t.slope_per_day AS temp_slope,
    t.recent_avg    AS temp_now,
    -- days to alarm threshold (vib alarm = 2.5x baseline), only when rising
    CASE WHEN v.slope_per_day > 0.01
         THEN GREATEST((v.base_med*2.5 - v.recent_avg) / v.slope_per_day, 0)
         ELSE NULL END AS days_to_threshold
  FROM v JOIN t ON t.asset_id = v.asset_id;

  -- 4) Insert new events (idempotent: skip assets with an open event of same mode).
  INSERT INTO ANALYTICS.ANOMALY_EVENTS
        (asset_id, detected_ts, anomaly_type, probable_mode, severity, score,
         days_to_threshold, feature_json, status)
  SELECT
    vd.asset_id,
    CURRENT_TIMESTAMP(),
    vd.probable_mode || '_PATTERN',
    vd.probable_mode,
    CASE
      WHEN vd.probable_mode = 'SENSOR_FAULT' THEN 'LOW'
      WHEN am.criticality = 'HIGH'
           AND (vd.days_to_threshold < 7 OR vd.vib_z > 10)      THEN 'HIGH'
      WHEN vd.days_to_threshold < 3                             THEN 'HIGH'
      ELSE 'MEDIUM'
    END,
    LEAST(ROUND(GREATEST(vd.vib_z, vd.temp_z) / 15, 2), 1.0),
    ROUND(vd.days_to_threshold, 1),
    OBJECT_CONSTRUCT(
      'vib_z', ROUND(vd.vib_z,2), 'vib_slope_per_day', ROUND(vd.vib_slope,3),
      'vib_now', ROUND(vd.vib_now,2), 'vib_baseline', ROUND(vd.vib_base,2),
      'vib_std_recent', ROUND(vd.vib_std,4),
      'temp_z', ROUND(vd.temp_z,2), 'temp_slope_per_day', ROUND(vd.temp_slope,3),
      'temp_now', ROUND(vd.temp_now,1),
      'rule_version', 'v1-G1'),
    'NEW'
  FROM _VERDICTS vd
  JOIN ERP.ASSET_MASTER am ON am.asset_id = vd.asset_id
  WHERE vd.probable_mode IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM ANALYTICS.ANOMALY_EVENTS e
      WHERE e.asset_id = vd.asset_id
        AND e.probable_mode = vd.probable_mode
        AND e.status IN ('NEW','INVESTIGATING','ACTIONED')
    );
  inserted := SQLROWCOUNT;

  -- 5) Detection succeeded — NOW consume the stream and log the batch.
  CREATE TABLE IF NOT EXISTS ANALYTICS.PROCESSED_BATCH_LOG (
    batch_id        NUMBER IDENTITY,
    batch_ts        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    rows_processed  NUMBER,
    min_ts          TIMESTAMP_NTZ,
    max_ts          TIMESTAMP_NTZ
  );

  INSERT INTO ANALYTICS.PROCESSED_BATCH_LOG (batch_ts, rows_processed, min_ts, max_ts)
  SELECT CURRENT_TIMESTAMP(), COUNT(*), MIN(ts), MAX(ts)
  FROM OT.TELEMETRY_STREAM;

  RETURN 'Processed ' || :new_rows || ' new rows; opened ' || :inserted || ' event(s).';
END;
$$;

-- ── Autonomous trigger ──────────────────────────────────────────────────────
-- Serverless task: wakes only when the stream has data; no-ops cost nothing.

CREATE OR REPLACE TASK ANALYTICS.DETECT_TASK
  SCHEDULE = '1 MINUTE'
  USER_TASK_MANAGED_INITIAL_WAREHOUSE_SIZE = 'XSMALL'
  WHEN SYSTEM$STREAM_HAS_DATA('OEE_DB.OT.TELEMETRY_STREAM')
AS
  CALL ANALYTICS.DETECT_ANOMALIES();

-- Created suspended by default. Resume deliberately:
-- ALTER TASK ANALYTICS.DETECT_TASK RESUME;
