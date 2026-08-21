-- 07_semantic_agent.sql — Cortex-native NL layer: semantic view + agent.
-- Objects CREATE successfully on trial accounts; only invocation
-- (DATA_AGENT_RUN / Cortex Analyst runtime) is gated — documented in README.
-- If syntax has drifted on the current platform version, adapt minimally
-- and keep names/structure.

-- ── Semantic view: the plant, queryable in business language ───────────────
CREATE OR REPLACE SEMANTIC VIEW OEE_DB.ANALYTICS.PLANT_SEMANTIC_VIEW
  TABLES (
    assets AS OEE_DB.ERP.ASSET_MASTER
      PRIMARY KEY (ASSET_ID)
      WITH SYNONYMS ('machines', 'equipment')
      COMMENT = 'Plant equipment master',
    events AS OEE_DB.ANALYTICS.ANOMALY_EVENTS
      PRIMARY KEY (EVENT_ID)
      WITH SYNONYMS ('faults', 'alerts', 'anomalies')
      COMMENT = 'Detected fault events with fault_pattern_id',
    work_orders AS OEE_DB.ANALYTICS.WORK_ORDERS_GENERATED
      PRIMARY KEY (WO_ID)
      WITH SYNONYMS ('maintenance orders', 'repairs scheduled')
      COMMENT = 'Autonomously generated maintenance work orders',
    reports AS OEE_DB.ANALYTICS.EXTRACTED_REPORTS
      PRIMARY KEY (REPORT_ID)
      WITH SYNONYMS ('repair reports', 'maintenance history documents')
      COMMENT = 'Fields extracted from scanned handwritten repair reports'
  )
  RELATIONSHIPS (
    events_to_assets AS events (ASSET_ID) REFERENCES assets,
    wo_to_assets AS work_orders (ASSET_ID) REFERENCES assets,
    reports_to_assets AS reports (ASSET_ID) REFERENCES assets
  )
  DIMENSIONS (
    assets.asset_id AS ASSET_ID,
    assets.asset_name AS ASSET_NAME,
    assets.line_id AS LINE_ID WITH SYNONYMS ('production line'),
    assets.criticality AS CRITICALITY,
    events.failure_mode AS PROBABLE_MODE WITH SYNONYMS ('fault type'),
    events.fault_pattern AS FAULT_PATTERN_ID,
    events.severity AS SEVERITY,
    events.event_status AS STATUS,
    work_orders.tier AS TIER,
    work_orders.wo_status AS STATUS,
    reports.report_pattern AS FAULT_PATTERN_ID
  )
  METRICS (
    events.event_count AS COUNT(EVENT_ID)
      COMMENT = 'Number of fault events',
    work_orders.wo_count AS COUNT(WO_ID)
      COMMENT = 'Number of work orders',
    reports.report_count AS COUNT(REPORT_ID)
      COMMENT = 'Number of historical repair reports'
  )
  COMMENT = 'ForgePulse plant semantic model: assets, faults, work orders, repair history';

-- ── Cortex Agent: NL interface over the semantic model ─────────────────────
CREATE OR REPLACE AGENT OEE_DB.ANALYTICS.FORGEPULSE_AGENT
  COMMENT = 'NL agent over the predictive-maintenance model. Invocation gated on trial accounts (DATA_AGENT_RUN); definition maintained for entitled environments.'
  PROFILE = '{"display_name": "ForgePulse Plant Agent"}'
  FROM SPECIFICATION
$$
models:
  orchestration: auto

instructions:
  response: |
    You answer questions about the ForgePulse plant: asset health, fault
    events, work orders, and repair history. Ground every answer in query
    results; quote asset ids, wo ids, and report ids. Rules are the
    authoritative fault verdict; the ML classifier is advisory.

tools:
  - tool_spec:
      type: cortex_analyst_text_to_sql
      name: plant_analyst
      description: Query the plant semantic view for assets, faults, work orders, repair history.

tool_resources:
  plant_analyst:
    semantic_view: OEE_DB.ANALYTICS.PLANT_SEMANTIC_VIEW
$$;

-- verify
SHOW SEMANTIC VIEWS IN SCHEMA OEE_DB.ANALYTICS;
SHOW AGENTS IN SCHEMA OEE_DB.ANALYTICS;
