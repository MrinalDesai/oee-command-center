---
name: failure-prediction
description: Assess current failure risk for any asset in the ForgePulse fleet - computes live engineered features, runs the registered fault classifier, and reports pattern probability with days-to-threshold. Use when asked "is asset X healthy", "what is failing", "predict failures", or "which machines need attention".
---

# Failure prediction

Predict developing faults for one asset or the whole fleet using the same
signals the autonomous DETECT layer uses.

## Data sources (fully qualified, read-only)
- `OEE_DB.OT.RAW_TELEMETRY` - live sensor readings (vibration mm/s RMS,
  bearing temp C, RPM, current A)
- `OEE_DB.ANALYTICS.ANOMALY_EVENTS` - open events with `fault_pattern_id`
- `OEE_DB.ANALYTICS.FAULT_PATTERN_CATALOG` - FP-01..FP-04 definitions
- Model: `OEE_DB.ANALYTICS.FAULT_PATTERN_CLASSIFIER` (Model Registry,
  latest version) - classes NORMAL, FP-01..FP-04

## Procedure
1. Baseline per sensor = MEDIAN(value) over days -31..-3 relative to
   MAX(ts). Recent = last 24h averages.
2. Features (must match training definitions in `src/generate_training.py`):
   vib_z (vs MAD of window start), vib_slope per day, vib_std_recent (6h),
   vib_ratio, temp_z, temp_slope, vib_temp_lagcorr (3h lag).
   RPM features are EXCLUDED (production-schedule regime shifts - see README).
3. Classify: prefer Registry SQL inference
   (`WITH m AS MODEL OEE_DB.ANALYTICS.FAULT_PATTERN_CLASSIFIER SELECT m!PREDICT_PROBA(...)`);
   if unavailable in this session, report the rule-layer verdict from
   ANOMALY_EVENTS and say which path was used.
4. days_to_threshold = (threshold - current) / slope, only when slope > 0.
5. Report per asset: pattern, confidence, top drivers with values, trend.

## Rules
- Deterministic rules are the floor: never report a lower severity than an
  open ANOMALY_EVENTS row for the asset.
- Never invent readings; every number quoted must come from a query result.
- If data is insufficient (fewer than 10 buckets), say so instead of guessing.
