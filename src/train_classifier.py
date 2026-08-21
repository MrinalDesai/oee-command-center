"""
train_classifier.py — Fault-pattern classifier: train, evaluate, explain,
and log to the Snowflake Model Registry.

Doctrine: the classifier adds nuance ON TOP of the deterministic rules —
it never replaces the stuck-at floor or the tier gates.

Usage:
    python src/train_classifier.py                 # train + eval + SHAP
    python src/train_classifier.py --register      # also log to Registry
Env for --register: SNOWFLAKE_ACCOUNT/USER/PASSWORD  (scripts/env.ps1)
Deps: xgboost scikit-learn shap pandas snowflake-ml-python
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

FEATURES = ["vib_z", "vib_slope", "vib_std_recent", "vib_ratio",
            "temp_z", "temp_slope", "vib_temp_lagcorr"]
# rpm_cv / rpm_osc excluded: live RPM carries production-schedule regime shifts the
# training sim cannot faithfully reproduce; documented in README (train/serve skew).


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/training.csv")
    ap.add_argument("--register", action="store_true")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    print("=== per-class feature means (training) ===")
    print(df.groupby("label")[FEATURES].mean().round(2))
    le = LabelEncoder()
    y = le.fit_transform(df["label"])
    X = df[FEATURES]

    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=7)

    model = XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.1,
        objective="multi:softprob", eval_metric="mlogloss",
        random_state=7)
    model.fit(Xtr, ytr)

    pred = model.predict(Xte)
    print("=== held-out evaluation (25%) ===")
    print(classification_report(yte, pred, target_names=le.classes_))
    print("confusion matrix (rows=true):")
    cm = confusion_matrix(yte, pred)
    print(pd.DataFrame(cm, index=le.classes_, columns=le.classes_))

    # explainability: SHAP mean |contribution| per feature
    try:
        import shap
        expl = shap.TreeExplainer(model)
        sv = expl.shap_values(Xte)
        import numpy as np
        mean_abs = np.abs(np.array(sv)).mean(axis=(0, 1))
        print("\n=== SHAP mean|contribution| per feature ===")
        for f, v in sorted(zip(FEATURES, mean_abs), key=lambda t: -t[1]):
            print(f"  {f:>18}: {v:.4f}")
    except Exception as e:
        print(f"(shap skipped: {e})")

    import json, os as _os
    _os.makedirs("data", exist_ok=True)
    model.save_model("data/fault_classifier.json")
    json.dump(list(le.classes_), open("data/fault_classes.json","w"))
    print("model saved -> data/fault_classifier.json")

    if args.register:
        missing = [k for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER",
                               "SNOWFLAKE_PASSWORD") if not os.environ.get(k)]
        if missing:
            sys.exit(f"Missing env vars: {', '.join(missing)}")
        from snowflake.snowpark import Session
        from snowflake.ml.registry import Registry
        s = Session.builder.configs({
            "account": os.environ["SNOWFLAKE_ACCOUNT"],
            "user": os.environ["SNOWFLAKE_USER"],
            "password": os.environ["SNOWFLAKE_PASSWORD"],
            "warehouse": "OEE_WH", "database": "OEE_DB",
            "schema": "ANALYTICS"}).create()
        r = Registry(session=s, database_name="OEE_DB", schema_name="ANALYTICS")
        mv = r.log_model(
            model,
            model_name="FAULT_PATTERN_CLASSIFIER",
            sample_input_data=Xtr.head(5),
            comment=("XGBoost fault-pattern classifier. Classes: "
                     + ", ".join(le.classes_)
                     + ". Adds probability on top of deterministic rules; "
                       "never overrides the stuck-at floor or tier gates."),
            metrics={"test_accuracy": float((pred == yte).mean())},
        )
        print(f"\nregistered: {mv.model_name} version {mv.version_name}")
        print("SQL inference template:")
        print('  WITH m AS MODEL OEE_DB.ANALYTICS.FAULT_PATTERN_CLASSIFIER')
        print('  SELECT m!PREDICT_PROBA(vib_z, vib_slope, ...) FROM <features>;')
        s.close()


if __name__ == "__main__":
    main()
