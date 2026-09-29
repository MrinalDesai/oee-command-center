"""Fleet failure prediction via Model Registry mv.run()."""

import json, os
import numpy as np
import pandas as pd
from snowflake.snowpark import Session
from snowflake.ml.registry import Registry

os.environ["PYTHONIOENCODING"] = "utf-8"

session = Session.builder.configs({"connection_name": "gcc_sub"}).create()
session.use_database("OEE_DB")
session.use_schema("ANALYTICS")

with open(r"C:\dev\oee-command-center\data\fault_classes.json") as f:
    CLASS_NAMES = json.load(f)

reg = Registry(session=session, database_name="OEE_DB", schema_name="ANALYTICS")
mv = reg.get_model("FAULT_PATTERN_CLASSIFIER").version("v1")

FEATURES = ["vib_z", "vib_slope", "vib_std_recent", "vib_ratio",
            "temp_z", "temp_slope", "vib_temp_lagcorr"]

# Recompute features inside Snowflake, pull as pandas
fleet = session.sql("""
    WITH bounds AS (
        SELECT MAX(ts) AS now_ts FROM OEE_DB.OT.RAW_TELEMETRY
    ),
    baseline_med AS (
        SELECT r.asset_id, r.sensor_type, MEDIAN(r.value) AS base_med
        FROM OEE_DB.OT.RAW_TELEMETRY r, bounds b
        WHERE r.ts BETWEEN DATEADD(day,-31,b.now_ts) AND DATEADD(day,-3,b.now_ts)
          AND r.quality_flag = 'GOOD'
        GROUP BY r.asset_id, r.sensor_type
    ),
    baseline_deviations AS (
        SELECT r.asset_id, r.sensor_type, ABS(r.value - bm.base_med) AS abs_dev
        FROM OEE_DB.OT.RAW_TELEMETRY r
        JOIN bounds b ON 1=1
        JOIN baseline_med bm ON bm.asset_id = r.asset_id AND bm.sensor_type = r.sensor_type
        WHERE r.ts BETWEEN DATEADD(day,-31,b.now_ts) AND DATEADD(day,-3,b.now_ts)
          AND r.quality_flag = 'GOOD'
    ),
    baseline AS (
        SELECT bd.asset_id, bd.sensor_type, bm.base_med,
               GREATEST(MEDIAN(bd.abs_dev), 0.001) AS base_mad
        FROM baseline_deviations bd
        JOIN baseline_med bm ON bm.asset_id = bd.asset_id AND bm.sensor_type = bd.sensor_type
        GROUP BY bd.asset_id, bd.sensor_type, bm.base_med
    ),
    recent AS (
        SELECT r.asset_id, r.sensor_type,
               AVG(r.value) AS recent_avg, STDDEV(r.value) AS recent_std, COUNT(*) AS n_recent
        FROM OEE_DB.OT.RAW_TELEMETRY r, bounds b
        WHERE r.ts > DATEADD(hour,-24,b.now_ts)
        GROUP BY r.asset_id, r.sensor_type
    ),
    recent_6h AS (
        SELECT r.asset_id, r.sensor_type, STDDEV(r.value) AS std_6h
        FROM OEE_DB.OT.RAW_TELEMETRY r, bounds b
        WHERE r.ts > DATEADD(hour,-6,b.now_ts)
        GROUP BY r.asset_id, r.sensor_type
    ),
    slope AS (
        SELECT r.asset_id, r.sensor_type,
               REGR_SLOPE(r.value, DATEDIFF(second,'1970-01-01',r.ts)/86400.0) AS slope_per_day
        FROM OEE_DB.OT.RAW_TELEMETRY r, bounds b
        WHERE r.ts > DATEADD(hour,-72,b.now_ts)
        GROUP BY r.asset_id, r.sensor_type
    ),
    lagcorr AS (
        SELECT v.asset_id, CORR(v.value, t.value) AS vib_temp_lagcorr
        FROM OEE_DB.OT.RAW_TELEMETRY v
        JOIN OEE_DB.OT.RAW_TELEMETRY t
          ON t.asset_id = v.asset_id AND t.sensor_type = 'BEARING_TEMP'
         AND t.ts = DATEADD(hour, -3, v.ts)
        JOIN bounds b ON 1=1
        WHERE v.sensor_type = 'VIBRATION_RMS' AND v.ts > DATEADD(hour,-24,b.now_ts)
        GROUP BY v.asset_id
    ),
    features AS (
        SELECT
            v_bl.asset_id,
            ROUND((v_rc.recent_avg - v_bl.base_med) / v_bl.base_mad, 2) AS vib_z,
            ROUND(v_sl.slope_per_day, 4) AS vib_slope,
            ROUND(COALESCE(v_6h.std_6h, v_rc.recent_std), 4) AS vib_std_recent,
            ROUND(v_rc.recent_avg / NULLIF(v_bl.base_med, 0), 4) AS vib_ratio,
            ROUND((t_rc.recent_avg - t_bl.base_med) / t_bl.base_mad, 2) AS temp_z,
            ROUND(t_sl.slope_per_day, 4) AS temp_slope,
            ROUND(COALESCE(lc.vib_temp_lagcorr, 0), 4) AS vib_temp_lagcorr,
            ROUND(v_rc.recent_avg, 2) AS vib_now,
            ROUND(v_bl.base_med, 2) AS vib_baseline,
            ROUND(t_rc.recent_avg, 1) AS temp_now,
            ROUND(t_bl.base_med, 1) AS temp_baseline,
            CASE WHEN v_sl.slope_per_day > 0.01
                 THEN ROUND(GREATEST((v_bl.base_med * 2.5 - v_rc.recent_avg) / v_sl.slope_per_day, 0), 1)
                 ELSE NULL END AS days_to_threshold
        FROM baseline v_bl
        JOIN baseline t_bl ON t_bl.asset_id = v_bl.asset_id AND t_bl.sensor_type = 'BEARING_TEMP'
        JOIN recent v_rc ON v_rc.asset_id = v_bl.asset_id AND v_rc.sensor_type = 'VIBRATION_RMS'
        JOIN recent t_rc ON t_rc.asset_id = v_bl.asset_id AND t_rc.sensor_type = 'BEARING_TEMP'
        JOIN slope v_sl ON v_sl.asset_id = v_bl.asset_id AND v_sl.sensor_type = 'VIBRATION_RMS'
        JOIN slope t_sl ON t_sl.asset_id = v_bl.asset_id AND t_sl.sensor_type = 'BEARING_TEMP'
        LEFT JOIN recent_6h v_6h ON v_6h.asset_id = v_bl.asset_id AND v_6h.sensor_type = 'VIBRATION_RMS'
        LEFT JOIN lagcorr lc ON lc.asset_id = v_bl.asset_id
        WHERE v_bl.sensor_type = 'VIBRATION_RMS'
    )
    SELECT f.*,
           am.asset_name, am.criticality,
           e.event_id AS open_event,
           e.probable_mode AS rule_verdict,
           e.severity AS rule_severity
    FROM features f
    JOIN OEE_DB.ERP.ASSET_MASTER am ON am.asset_id = f.asset_id
    LEFT JOIN OEE_DB.ANALYTICS.ANOMALY_EVENTS e
      ON e.asset_id = f.asset_id AND e.status IN ('NEW','INVESTIGATING','ACTIONED')
""").to_pandas()

# Lowercase the feature columns for the model
input_df = fleet[["VIB_Z","VIB_SLOPE","VIB_STD_RECENT","VIB_RATIO",
                   "TEMP_Z","TEMP_SLOPE","VIB_TEMP_LAGCORR"]].copy()
input_df.columns = FEATURES

proba_result = mv.run(input_df, function_name="predict_proba")
proba_cols = sorted([c for c in proba_result.columns if c.startswith("output_feature_")])
proba_arr = proba_result[proba_cols].values

fleet["predicted_idx"] = proba_arr.argmax(axis=1)
fleet["predicted_pattern"] = [CLASS_NAMES[i] for i in fleet["predicted_idx"]]
fleet["confidence"] = proba_arr.max(axis=1)
for i, name in enumerate(CLASS_NAMES):
    fleet[f"prob_{name}"] = proba_arr[:, i]

fleet = fleet.sort_values(
    by=["predicted_pattern", "confidence", "DAYS_TO_THRESHOLD"],
    key=lambda col: col if col.name != "predicted_pattern"
                    else col.map(lambda x: 1 if x == "NORMAL" else 0),
    ascending=[True, False, True],
).reset_index(drop=True)

print("=" * 105)
print("FLEET FAILURE PREDICTION  |  Model: FAULT_PATTERN_CLASSIFIER v1 (mv.run, predict_proba)")
print("=" * 105)

for _, r in fleet.iterrows():
    tag = ""
    if pd.notna(r.get("OPEN_EVENT")):
        tag = f"  [EVENT #{int(r['OPEN_EVENT'])}: {r['RULE_VERDICT']} / {r['RULE_SEVERITY']}]"
    dtt = f"{r['DAYS_TO_THRESHOLD']:.1f}d" if pd.notna(r["DAYS_TO_THRESHOLD"]) else "n/a"

    print(f"\n{r['ASSET_ID']}  {r['ASSET_NAME']:<28s}  crit={r['CRITICALITY']}{tag}")
    print(f"  Predicted: {r['predicted_pattern']:<10s}  confidence={r['confidence']:.4f}  days_to_threshold={dtt}")
    print(f"  Features:  vib_z={r['VIB_Z']:.2f}  slope={r['VIB_SLOPE']:.4f}  "
          f"std={r['VIB_STD_RECENT']:.4f}  ratio={r['VIB_RATIO']:.4f}  "
          f"temp_z={r['TEMP_Z']:.2f}  t_slope={r['TEMP_SLOPE']:.4f}  "
          f"lagcorr={r['VIB_TEMP_LAGCORR']:.4f}")
    probs = "  ".join(f"{n}={r[f'prob_{n}']:.4f}" for n in CLASS_NAMES)
    print(f"  Proba:     {probs}")

print("\n" + "=" * 105)
non_normal = fleet[fleet["predicted_pattern"] != "NORMAL"]
within_7d = non_normal[non_normal["DAYS_TO_THRESHOLD"].fillna(9999) <= 7]
print(f"Fault-flagged: {len(non_normal)}/{len(fleet)}    Within 7d threshold: {len(within_7d)}/{len(fleet)}")
print("=" * 105)

session.close()
