"""Register the pre-trained XGBoost fault classifier in Snowflake Model Registry
and run one inference against the AST-007 detection window."""

import json, os
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from snowflake.snowpark import Session
from snowflake.ml.registry import Registry

os.environ["PYTHONIOENCODING"] = "utf-8"

# ── 1. Snowpark session ──────────────────────────────────────────────────────
session = Session.builder.configs({"connection_name": "gcc_sub"}).create()
session.use_database("OEE_DB")
session.use_schema("ANALYTICS")
print("Connected:", session.get_current_database(), session.get_current_schema())

# ── 2. Load pre-trained model (no retraining) ────────────────────────────────
with open(r"C:\dev\oee-command-center\data\fault_classes.json") as f:
    CLASS_NAMES = json.load(f)

model = XGBClassifier()
model.load_model(r"C:\dev\oee-command-center\data\fault_classifier.json")

# Model was trained with lowercase feature names
FEATURES = [
    "vib_z", "vib_slope", "vib_std_recent",
    "vib_ratio", "temp_z", "temp_slope", "vib_temp_lagcorr",
]

print(f"Model loaded: {model.n_classes_} classes, {model.n_features_in_} features")
print(f"Classes: {CLASS_NAMES}")
print(f"Model feature names: {model.feature_names_in_}")

# ── 3. Build sample input for registry (lowercase to match training) ──────────
sample_input = pd.DataFrame(
    [[0.0] * len(FEATURES)],
    columns=FEATURES,
)

# ── 4. Register in Model Registry ─────────────────────────────────────────────
reg = Registry(session=session, database_name="OEE_DB", schema_name="ANALYTICS")

mv = reg.log_model(
    model,
    model_name="FAULT_PATTERN_CLASSIFIER",
    version_name="v1",
    sample_input_data=sample_input,
    conda_dependencies=["xgboost"],
    options={"relax_version": False},
    comment="Pre-trained XGBoost multi-class fault classifier (FP-01..FP-04, NORMAL). "
            "7 features, loaded from data/fault_classifier.json. Not retrained.",
)

print(f"\nRegistered: {mv.model_name} version {mv.version_name}")
print("Functions:", mv.show_functions())

# ── 5. Inference: fetch AST-007 detection features and predict ────────────────
row = session.sql("""
    SELECT
        f.feature_json:"vib_z"::FLOAT              AS "vib_z",
        f.feature_json:"vib_slope_per_day"::FLOAT   AS "vib_slope",
        f.feature_json:"vib_std_recent"::FLOAT      AS "vib_std_recent",
        f.feature_json:"vib_now"::FLOAT
          / NULLIF(f.feature_json:"vib_baseline"::FLOAT, 0) AS "vib_ratio",
        f.feature_json:"temp_z"::FLOAT              AS "temp_z",
        f.feature_json:"temp_slope_per_day"::FLOAT  AS "temp_slope",
        0.0                                          AS "vib_temp_lagcorr"
    FROM OEE_DB.ANALYTICS.ANOMALY_EVENTS f
    WHERE f.asset_id = 'AST-007'
      AND f.probable_mode = 'BEARING_WEAR'
    ORDER BY f.detected_ts DESC
    LIMIT 1
""").to_pandas()

print("\n-- AST-007 feature vector --")
print(row.to_string(index=False))

# Local predict
features_np = row[FEATURES].values.astype(np.float32)
proba = model.predict_proba(features_np)[0]
pred_idx = int(proba.argmax())
pred_class = CLASS_NAMES[pred_idx]

print(f"\n-- Prediction --")
print(f"Predicted pattern : {pred_class}")
print(f"Confidence        : {proba[pred_idx]:.4f}")
print(f"\nAll class probabilities:")
for i, (cls, p) in enumerate(zip(CLASS_NAMES, proba)):
    bar = "#" * int(p * 40)
    print(f"  {cls:<10s} {p:.4f}  {bar}")

# Also run via registry (warehouse inference) to confirm it works
print("\n-- Registry inference (mv.run) --")
result = mv.run(row[FEATURES], function_name="predict")
print(result.to_string(index=False))

session.close()
print("\nDone.")
