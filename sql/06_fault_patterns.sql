-- 06_fault_patterns.sql — fault-pattern catalog, wired into detection.
-- Links live events to the historical report corpus (reports_index.csv)
-- via fault_pattern_id. Fully qualified names throughout.

-- ── Catalog ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS OEE_DB.ANALYTICS.FAULT_PATTERN_CATALOG (
  fault_pattern_id VARCHAR(6) PRIMARY KEY,
  fault_mode       VARCHAR(30),
  description      VARCHAR(400)
);

MERGE INTO OEE_DB.ANALYTICS.FAULT_PATTERN_CATALOG t
USING (SELECT * FROM VALUES
  ('FP-01','BEARING_WEAR',
   'Vibration climbs exponentially over days; bearing temp follows with lag; RPM stays stable. Ends in seizure if unaddressed.'),
  ('FP-02','COOLING_DEGRADATION',
   'Temperature trends up over 1-3 weeks while vibration stays normal. Fouled coolers, blocked filters, scaling.'),
  ('FP-03','SENSOR_FAULT',
   'Signal variance collapses to near zero (stuck-at) or flatlines while the machine is demonstrably running. Data-quality issue, never a parts dispatch.'),
  ('FP-04','BELT_SLIP_RPM',
   'Speed hunting: periodic RPM oscillation with slip dips under load. Belt tension/glazing/sheave wear on belt-driven units.')
) s(fault_pattern_id, fault_mode, description)
ON t.fault_pattern_id = s.fault_pattern_id
WHEN NOT MATCHED THEN INSERT (fault_pattern_id, fault_mode, description)
  VALUES (s.fault_pattern_id, s.fault_mode, s.description);

-- ── Event linkage ───────────────────────────────────────────────────────────
ALTER TABLE OEE_DB.ANALYTICS.ANOMALY_EVENTS ADD COLUMN IF NOT EXISTS
  fault_pattern_id VARCHAR(6);

-- Backfill any existing events
UPDATE OEE_DB.ANALYTICS.ANOMALY_EVENTS e
SET fault_pattern_id = c.fault_pattern_id
FROM OEE_DB.ANALYTICS.FAULT_PATTERN_CATALOG c
WHERE c.fault_mode = e.probable_mode
  AND e.fault_pattern_id IS NULL;

-- ── Proc change (hand to CoCo as instruction, not runnable here) ────────────
-- In OEE_DB.ANALYTICS.DETECT_ANOMALIES, the INSERT INTO ANOMALY_EVENTS gains:
--   fault_pattern_id = (SELECT c.fault_pattern_id
--                       FROM OEE_DB.ANALYTICS.FAULT_PATTERN_CATALOG c
--                       WHERE c.fault_mode = vd.probable_mode)
-- i.e. add the column to the insert list and the subquery (or a join) to the
-- SELECT. BELT_SLIP_RPM detection itself lands with the classifier (G2);
-- the catalog row exists now so reports and events share one ID space.
