-- 08_load.sql — Stage creation, PUT, and COPY for all 5 CSV datasets.
-- Prerequisite: sql/01_schema.sql executed; CSVs present in data/.
-- Fully qualified names throughout. Idempotent (OVERWRITE + TRUNCATECOLUMNS).

-- ── Stage ────────────────────────────────────────────────────────────────────
CREATE OR REPLACE STAGE OEE_DB.OT.CSV_LOAD_STAGE
  FILE_FORMAT = (TYPE = 'CSV' SKIP_HEADER = 1
                 FIELD_OPTIONALLY_ENCLOSED_BY = '"'
                 NULL_IF = ('','NULL'));

-- ── PUT (client-side upload — adjust file:// path to your local checkout) ────
PUT file://C:/dev/oee-command-center/data/raw_telemetry.csv        @OEE_DB.OT.CSV_LOAD_STAGE/telemetry    AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
PUT file://C:/dev/oee-command-center/data/asset_master.csv         @OEE_DB.OT.CSV_LOAD_STAGE/asset_master AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
PUT file://C:/dev/oee-command-center/data/work_order_history.csv   @OEE_DB.OT.CSV_LOAD_STAGE/work_orders  AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
PUT file://C:/dev/oee-command-center/data/spare_parts_inventory.csv @OEE_DB.OT.CSV_LOAD_STAGE/spare_parts AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
PUT file://C:/dev/oee-command-center/data/production_schedule.csv  @OEE_DB.OT.CSV_LOAD_STAGE/production   AUTO_COMPRESS=TRUE OVERWRITE=TRUE;

-- ── COPY INTO ────────────────────────────────────────────────────────────────
-- Truncate targets first for idempotent re-runs.
TRUNCATE TABLE IF EXISTS OEE_DB.OT.RAW_TELEMETRY;
TRUNCATE TABLE IF EXISTS OEE_DB.ERP.ASSET_MASTER;
TRUNCATE TABLE IF EXISTS OEE_DB.ERP.WORK_ORDER_HISTORY;
TRUNCATE TABLE IF EXISTS OEE_DB.ERP.SPARE_PARTS_INVENTORY;
TRUNCATE TABLE IF EXISTS OEE_DB.ERP.PRODUCTION_SCHEDULE;

COPY INTO OEE_DB.OT.RAW_TELEMETRY (asset_id, sensor_type, ts, value, quality_flag)
FROM @OEE_DB.OT.CSV_LOAD_STAGE/telemetry
FILE_FORMAT = (TYPE = 'CSV' SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"' NULL_IF = ('','NULL'))
ON_ERROR = 'ABORT_STATEMENT'
PURGE = FALSE;

COPY INTO OEE_DB.ERP.ASSET_MASTER (asset_id, asset_name, asset_type, line_id, model_no, install_date, criticality)
FROM @OEE_DB.OT.CSV_LOAD_STAGE/asset_master
FILE_FORMAT = (TYPE = 'CSV' SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"' NULL_IF = ('','NULL'))
ON_ERROR = 'ABORT_STATEMENT'
PURGE = FALSE;

COPY INTO OEE_DB.ERP.WORK_ORDER_HISTORY (wo_id, asset_id, wo_type, opened_ts, closed_ts, failure_mode, technician_notes, parts_used, downtime_hours)
FROM @OEE_DB.OT.CSV_LOAD_STAGE/work_orders
FILE_FORMAT = (TYPE = 'CSV' SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"' NULL_IF = ('','NULL'))
ON_ERROR = 'ABORT_STATEMENT'
PURGE = FALSE;

COPY INTO OEE_DB.ERP.SPARE_PARTS_INVENTORY (part_no, part_name, qty_on_hand, lead_time_days, unit_cost)
FROM @OEE_DB.OT.CSV_LOAD_STAGE/spare_parts
FILE_FORMAT = (TYPE = 'CSV' SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"' NULL_IF = ('','NULL'))
ON_ERROR = 'ABORT_STATEMENT'
PURGE = FALSE;

COPY INTO OEE_DB.ERP.PRODUCTION_SCHEDULE (line_id, shift_date, shift_no, planned_minutes, planned_units, actual_units, good_units)
FROM @OEE_DB.OT.CSV_LOAD_STAGE/production
FILE_FORMAT = (TYPE = 'CSV' SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"' NULL_IF = ('','NULL'))
ON_ERROR = 'ABORT_STATEMENT'
PURGE = FALSE;

-- ── Verify ───────────────────────────────────────────────────────────────────
-- Expected: 1,244,160 / 12 / 41 / 10 / 810
SELECT 'OEE_DB.OT.RAW_TELEMETRY' AS tbl, COUNT(*) AS rows FROM OEE_DB.OT.RAW_TELEMETRY
UNION ALL SELECT 'OEE_DB.ERP.ASSET_MASTER', COUNT(*) FROM OEE_DB.ERP.ASSET_MASTER
UNION ALL SELECT 'OEE_DB.ERP.WORK_ORDER_HISTORY', COUNT(*) FROM OEE_DB.ERP.WORK_ORDER_HISTORY
UNION ALL SELECT 'OEE_DB.ERP.SPARE_PARTS_INVENTORY', COUNT(*) FROM OEE_DB.ERP.SPARE_PARTS_INVENTORY
UNION ALL SELECT 'OEE_DB.ERP.PRODUCTION_SCHEDULE', COUNT(*) FROM OEE_DB.ERP.PRODUCTION_SCHEDULE;
