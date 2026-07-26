-- 01_schema.sql — OEE Command Center
-- Two worlds: OT (telemetry) + IT (ERP/maintenance)

CREATE DATABASE IF NOT EXISTS OEE_DB;
USE DATABASE OEE_DB;
CREATE SCHEMA IF NOT EXISTS OT;      -- sensor world
CREATE SCHEMA IF NOT EXISTS ERP;     -- business world
CREATE SCHEMA IF NOT EXISTS ANALYTICS; -- features, predictions, findings

CREATE WAREHOUSE IF NOT EXISTS OEE_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE;

-- ── OT world ─────────────────────────────────────────────
CREATE OR REPLACE TABLE OT.RAW_TELEMETRY (
  reading_id     NUMBER IDENTITY,
  asset_id       VARCHAR(20)  NOT NULL,
  sensor_type    VARCHAR(30)  NOT NULL,  -- VIBRATION_RMS | BEARING_TEMP | RPM | CURRENT_DRAW
  ts             TIMESTAMP_NTZ NOT NULL,
  value          FLOAT        NOT NULL,
  quality_flag   VARCHAR(10)  DEFAULT 'GOOD', -- GOOD | SUSPECT | BAD
  ingested_at    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- ── ERP world ────────────────────────────────────────────
CREATE OR REPLACE TABLE ERP.ASSET_MASTER (
  asset_id       VARCHAR(20) PRIMARY KEY,
  asset_name     VARCHAR(100),
  asset_type     VARCHAR(30),   -- MOTOR | PUMP | COMPRESSOR
  line_id        VARCHAR(10),
  model_no       VARCHAR(50),
  install_date   DATE,
  criticality    VARCHAR(10)    -- HIGH | MEDIUM | LOW
);

CREATE OR REPLACE TABLE ERP.WORK_ORDER_HISTORY (
  wo_id            VARCHAR(20) PRIMARY KEY,
  asset_id         VARCHAR(20),
  wo_type          VARCHAR(20),  -- CORRECTIVE | PREVENTIVE | PREDICTIVE
  opened_ts        TIMESTAMP_NTZ,
  closed_ts        TIMESTAMP_NTZ,
  failure_mode     VARCHAR(50),  -- BEARING_WEAR | COOLING_DEGRADATION | SENSOR_FAULT | NULL
  technician_notes VARCHAR(4000), -- free text -> Cortex Search
  parts_used       VARCHAR(500),
  downtime_hours   FLOAT
);

CREATE OR REPLACE TABLE ERP.SPARE_PARTS_INVENTORY (
  part_no        VARCHAR(30) PRIMARY KEY,
  part_name      VARCHAR(100),
  qty_on_hand    NUMBER,
  lead_time_days NUMBER,
  unit_cost      FLOAT
);

CREATE OR REPLACE TABLE ERP.PRODUCTION_SCHEDULE (
  line_id        VARCHAR(10),
  shift_date     DATE,
  shift_no       NUMBER,        -- 1..3
  planned_minutes NUMBER,
  planned_units  NUMBER,
  actual_units   NUMBER,
  good_units     NUMBER
);

-- ── Analytics world (pipeline outputs land here) ─────────
CREATE OR REPLACE TABLE ANALYTICS.ANOMALY_EVENTS (
  event_id       NUMBER IDENTITY,
  asset_id       VARCHAR(20),
  detected_ts    TIMESTAMP_NTZ,
  anomaly_type   VARCHAR(50),
  severity       VARCHAR(10),   -- HIGH | MEDIUM | LOW
  score          FLOAT,
  status         VARCHAR(20) DEFAULT 'NEW' -- NEW | INVESTIGATING | ACTIONED | DISMISSED
);

CREATE OR REPLACE TABLE ANALYTICS.FINDINGS (
  finding_id     NUMBER IDENTITY,
  event_id       NUMBER,
  asset_id       VARCHAR(20),
  rca_summary    VARCHAR(8000),  -- Cortex COMPLETE output
  evidence_json  VARIANT,        -- citations: telemetry stats + WO refs
  recommended_action VARCHAR(200),
  created_ts     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE TABLE ANALYTICS.WORK_ORDERS_GENERATED (
  wo_id          VARCHAR(20),
  finding_id     NUMBER,
  asset_id       VARCHAR(20),
  priority       VARCHAR(10),
  description    VARCHAR(4000),
  suggested_parts VARCHAR(500),
  status         VARCHAR(20) DEFAULT 'OPEN',
  created_ts     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);