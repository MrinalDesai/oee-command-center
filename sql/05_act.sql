-- 05_act.sql — OEE Command Center act layer (G1 spine, final vertebra)
-- Doctrine: tier assignment is DETERMINISTIC SQL — auditable in this file.
-- No LLM decides whether to act; the LLM (when available) only words things.
-- Tiers (FR-3):
--   A: HIGH severity, non-sensor  -> auto work order + notification (full autonomy)
--   B: MEDIUM, non-sensor         -> scheduled work order, awaits UI approval
--   C: SENSOR_FAULT               -> data-quality ticket; parts can never be ordered
-- All names fully qualified. Idempotent: one generated WO per finding.

-- ── Schema upgrades ─────────────────────────────────────────────────────────
ALTER TABLE OEE_DB.ANALYTICS.WORK_ORDERS_GENERATED ADD COLUMN IF NOT EXISTS
  tier VARCHAR(1);
ALTER TABLE OEE_DB.ANALYTICS.WORK_ORDERS_GENERATED ADD COLUMN IF NOT EXISTS
  scheduled_for DATE;
ALTER TABLE OEE_DB.ANALYTICS.WORK_ORDERS_GENERATED ADD COLUMN IF NOT EXISTS
  parts_availability VARCHAR(30);   -- IN_STOCK | PARTIAL | ORDER_REQUIRED | N/A

-- ── Act procedure ───────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE OEE_DB.ANALYTICS.ACT_ON_FINDINGS()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
  n_pending INTEGER DEFAULT 0;
  n_wo INTEGER DEFAULT 0;
  n_notif INTEGER DEFAULT 0;
BEGIN
  SELECT COUNT(*) INTO :n_pending
  FROM OEE_DB.ANALYTICS.FINDINGS f
  JOIN OEE_DB.ANALYTICS.ANOMALY_EVENTS e ON e.event_id = f.event_id
  WHERE e.status = 'INVESTIGATING'
    AND NOT EXISTS (SELECT 1 FROM OEE_DB.ANALYTICS.WORK_ORDERS_GENERATED w
                    WHERE w.finding_id = f.finding_id);
  IF (n_pending = 0) THEN
    RETURN 'No findings awaiting action.';
  END IF;

  -- 1) Decision table: tier + parts + schedule per pending finding.
  CREATE OR REPLACE TEMPORARY TABLE _ACTIONS AS
  WITH pending AS (
    SELECT f.finding_id, f.event_id, f.asset_id, f.recommended_action,
           e.probable_mode, e.severity, e.days_to_threshold
    FROM OEE_DB.ANALYTICS.FINDINGS f
    JOIN OEE_DB.ANALYTICS.ANOMALY_EVENTS e ON e.event_id = f.event_id
    WHERE e.status = 'INVESTIGATING'
      AND NOT EXISTS (SELECT 1 FROM OEE_DB.ANALYTICS.WORK_ORDERS_GENERATED w
                      WHERE w.finding_id = f.finding_id)
  ),
  -- parts historically used for this failure mode (from real WO history),
  -- resolved against current inventory
  mode_parts AS (
    SELECT p.finding_id,
           LISTAGG(DISTINCT sp.part_no, ', ') AS suggested_parts,
           CASE
             WHEN MIN(sp.qty_on_hand) IS NULL THEN 'N/A'
             WHEN MIN(sp.qty_on_hand) >= 2 THEN 'IN_STOCK'
             WHEN MIN(sp.qty_on_hand) >= 1 THEN 'PARTIAL'
             ELSE 'ORDER_REQUIRED'
           END AS parts_availability
    FROM pending p
    LEFT JOIN OEE_DB.ERP.WORK_ORDER_HISTORY wh
      ON wh.failure_mode = p.probable_mode AND wh.wo_type = 'CORRECTIVE'
    LEFT JOIN OEE_DB.ERP.SPARE_PARTS_INVENTORY sp
      ON POSITION(sp.part_no IN COALESCE(wh.parts_used,'')) > 0
    GROUP BY p.finding_id
  ),
  -- next low-load window on the asset's line: earliest future night shift
  -- (shift 3), the maintenance-friendly slot in the schedule
  next_window AS (
    SELECT p.finding_id, MIN(ps.shift_date) AS scheduled_for
    FROM pending p
    JOIN OEE_DB.ERP.ASSET_MASTER am ON am.asset_id = p.asset_id
    JOIN OEE_DB.ERP.PRODUCTION_SCHEDULE ps
      ON ps.line_id = am.line_id
     AND ps.shift_no = 3
     AND ps.shift_date >= CURRENT_DATE()
    GROUP BY p.finding_id
  )
  SELECT p.*,
         CASE
           WHEN p.probable_mode = 'SENSOR_FAULT' THEN 'C'
           WHEN p.severity = 'HIGH'              THEN 'A'
           ELSE 'B'
         END AS tier,
         CASE WHEN p.probable_mode = 'SENSOR_FAULT'
              THEN NULL ELSE mp.suggested_parts END AS suggested_parts,
         CASE WHEN p.probable_mode = 'SENSOR_FAULT'
              THEN 'N/A' ELSE COALESCE(mp.parts_availability,'N/A') END AS parts_availability,
         -- Tier A with imminent failure: tomorrow regardless of window.
         CASE
           WHEN p.probable_mode = 'SENSOR_FAULT' THEN CURRENT_DATE() + 1
           WHEN p.severity = 'HIGH' AND COALESCE(p.days_to_threshold, 0) < 2
                THEN CURRENT_DATE() + 1
           ELSE COALESCE(nw.scheduled_for, CURRENT_DATE() + 2)
         END AS scheduled_for
  FROM pending p
  LEFT JOIN mode_parts mp ON mp.finding_id = p.finding_id
  LEFT JOIN next_window nw ON nw.finding_id = p.finding_id;

  -- 2) Write the work orders.
  INSERT INTO OEE_DB.ANALYTICS.WORK_ORDERS_GENERATED
        (wo_id, finding_id, asset_id, priority, description,
         suggested_parts, status, tier, scheduled_for, parts_availability)
  SELECT
    'AWO-' || LPAD(TO_VARCHAR(a.finding_id), 5, '0'),
    a.finding_id, a.asset_id,
    CASE a.tier WHEN 'A' THEN 'HIGH' WHEN 'B' THEN 'MEDIUM' ELSE 'LOW' END,
    CASE a.tier
      WHEN 'C' THEN 'DATA QUALITY: ' || a.asset_id ||
                    ' sensor suspected faulty (stuck/invalid signal). Inspect ' ||
                    'sensor and cabling. No mechanical work authorized from this ticket.'
      ELSE 'PREDICTIVE: ' || a.asset_id || ' — ' || a.probable_mode ||
           ' detected (severity ' || a.severity ||
           COALESCE(', est. ' || a.days_to_threshold || ' days to alarm', '') ||
           '). ' || a.recommended_action ||
           '. See finding #' || a.finding_id || ' for evidence.'
    END,
    a.suggested_parts,
    CASE a.tier WHEN 'A' THEN 'OPEN' WHEN 'B' THEN 'AWAITING_APPROVAL'
                ELSE 'OPEN' END,
    a.tier, a.scheduled_for, a.parts_availability
  FROM _ACTIONS a;
  n_wo := SQLROWCOUNT;

  -- 3) Notifications: Tier A fires immediately; Tier C informs data quality.
  --    (Channel 'UI' = command-center queue; email integration is a later
  --     wiring — the LOG is the verifiable act.)
  INSERT INTO OEE_DB.ANALYTICS.NOTIFICATIONS_LOG
        (event_id, channel, recipient, payload)
  SELECT a.event_id, 'UI',
         CASE a.tier WHEN 'C' THEN 'data-quality-queue'
                     ELSE 'maintenance-planner' END,
         'Work order AWO-' || LPAD(TO_VARCHAR(a.finding_id),5,'0') ||
         ' [' || a.tier || '/' ||
         CASE a.tier WHEN 'A' THEN 'auto-dispatched'
                     WHEN 'B' THEN 'awaiting approval'
                     ELSE 'data-quality' END || '] ' ||
         a.asset_id || ' ' || COALESCE(a.probable_mode,'') ||
         ' scheduled ' || TO_VARCHAR(a.scheduled_for)
  FROM _ACTIONS a
  WHERE a.tier IN ('A','C');
  n_notif := SQLROWCOUNT;

  -- 4) Status machine: acted findings advance their events.
  UPDATE OEE_DB.ANALYTICS.ANOMALY_EVENTS e
  SET status = 'ACTIONED'
  WHERE e.status = 'INVESTIGATING'
    AND EXISTS (SELECT 1 FROM OEE_DB.ANALYTICS.FINDINGS f
                JOIN OEE_DB.ANALYTICS.WORK_ORDERS_GENERATED w
                  ON w.finding_id = f.finding_id
                WHERE f.event_id = e.event_id);

  RETURN 'Acted on ' || n_wo || ' finding(s): ' || n_wo ||
         ' work order(s), ' || n_notif || ' notification(s).';
END;
$$;

-- ── Complete the DAG: detect -> diagnose -> act ─────────────────────────────
-- (Root must be suspended to attach children; enable children first, root last.)
CREATE OR REPLACE TASK OEE_DB.ANALYTICS.ACT_TASK
  USER_TASK_MANAGED_INITIAL_WAREHOUSE_SIZE = 'XSMALL'
  AFTER OEE_DB.ANALYTICS.DIAGNOSE_TASK
AS
  CALL OEE_DB.ANALYTICS.ACT_ON_FINDINGS();

-- Enable sequence when ready to go fully autonomous:
-- ALTER TASK OEE_DB.ANALYTICS.ACT_TASK RESUME;
-- ALTER TASK OEE_DB.ANALYTICS.DIAGNOSE_TASK RESUME;
-- ALTER TASK OEE_DB.ANALYTICS.DETECT_TASK RESUME;
