"""
enrich_worker.py — Diagnosis enrichment: explainability + history + confidence.

For each finding, this worker:
  1. computes the same engineered features detection uses (from live data)
  2. runs the fault classifier -> per-class CONFIDENCE
  3. extracts the top contributing factors (SHAP) -> WHY the model thinks so
  4. embeds the symptoms (Cortex EMBED_TEXT_768) and retrieves the most similar past
     repair reports from REPORT_EMBEDDINGS (Snowflake VECTOR search)
  5. writes everything to OEE_DB.ANALYTICS.FINDING_ENRICHMENT
     for the console's Diagnosis panel.

Retrieval is fully in-account: the query is embedded by
SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', ...) inside the
similarity SQL, matching the 768-dim corpus built by sql/07_embed_reports.sql.
The previous local bge-m3/Ollama path (1024-dim) is retained in embed() as a
documented fallback for accounts where Cortex is gated.

Prereq: python src/train_classifier.py  (saves data/fault_classifier.json)
Run:    . .\\scripts\\env.ps1 ; python src\\enrich_worker.py        # once
        python src\\enrich_worker.py --loop                        # keep polling
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests
import snowflake.connector
import xgboost as xgb
import numpy as np

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
FEATURES = ["vib_z", "vib_slope", "vib_std_recent", "vib_ratio",
            "temp_z", "temp_slope", "vib_temp_lagcorr"]

SERIES_SQL = """
SELECT TIME_SLICE(ts, 5, 'MINUTE') tb, AVG(value) v
FROM OEE_DB.OT.RAW_TELEMETRY
WHERE asset_id=%(a)s AND sensor_type=%(s)s
  AND ts > DATEADD(day,-3,(SELECT MAX(ts) FROM OEE_DB.OT.RAW_TELEMETRY))
GROUP BY tb ORDER BY tb
"""
BASE_SQL = """
SELECT MEDIAN(value) FROM OEE_DB.OT.RAW_TELEMETRY
WHERE asset_id=%(a)s AND sensor_type=%(s)s
  AND ts BETWEEN DATEADD(day,-31,(SELECT MAX(ts) FROM OEE_DB.OT.RAW_TELEMETRY))
             AND DATEADD(day,-3,(SELECT MAX(ts) FROM OEE_DB.OT.RAW_TELEMETRY))
"""

import statistics as st
import math


def _slope_per_day(series, cadence_min=5):
    n = len(series)
    if n < 3:
        return 0.0
    xs = [i * cadence_min / 1440 for i in range(n)]
    mx, my = sum(xs) / n, sum(series) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, series))
    den = sum((x - mx) ** 2 for x in xs) or 1
    return num / den


def _lag_corr(a, b, lag=36):
    if len(a) <= lag + 2 or len(b) <= lag + 2:
        return 0.0
    a2, b2 = a[:-lag], b[lag:]
    m = min(len(a2), len(b2)); a2, b2 = a2[:m], b2[:m]
    ma, mb = sum(a2) / m, sum(b2) / m
    num = sum((x - ma) * (y - mb) for x, y in zip(a2, b2))
    da = math.sqrt(sum((x - ma) ** 2 for x in a2))
    db = math.sqrt(sum((y - mb) ** 2 for y in b2))
    return num / (da * db) if da and db else 0.0



def _roll_med_residual(series, k=12):
    if len(series) < k + 2:
        return [0.0] * len(series)
    import statistics as _st
    out = []
    for i in range(len(series)):
        lo = max(0, i - k)
        out.append(series[i] - _st.median(series[lo:i + 1]))
    return out


def compute_features(cur, asset):
    """Same formulas as generate_training.features(), on 5-min buckets."""
    def series(sensor):
        cur.execute(SERIES_SQL, {"a": asset, "s": sensor})
        return [float(r[1]) for r in cur.fetchall()]
    def base(sensor):
        cur.execute(BASE_SQL, {"a": asset, "s": sensor})
        v = cur.fetchone()[0]
        return float(v) if v else 1.0
    vib, temp, rpm = series("VIBRATION_RMS"), series("BEARING_TEMP"), series("RPM")
    vb, tb = base("VIBRATION_RMS"), base("BEARING_TEMP")
    if len(vib) < 10:
        raise ValueError(f"too little data for {asset}")
    third = vib[:max(3, len(vib) // 3)]
    med = st.median(third)
    mad = st.median([abs(x - med) for x in third]) or 0.01
    rec_v, rec_t = vib[-288:], temp[-288:]
    rec_r = rpm[-288:] if rpm else [1.0]
    return {
        "vib_z": (st.mean(rec_v) - vb) / mad,
        "vib_slope": _slope_per_day(vib),
        "vib_std_recent": st.pstdev(rec_v[-72:]) if len(rec_v) >= 2 else 0.0,
        "vib_ratio": st.mean(rec_v) / vb,
        "temp_z": (st.mean(rec_t) - tb) / 1.0 if temp else 0.0,
        "temp_slope": _slope_per_day(temp) if temp else 0.0,
        "rpm_cv": (st.pstdev(_roll_med_residual(rec_r)) / st.mean(rec_r)) if rpm else 0.0,
        "rpm_osc": (lambda res: (max(res) - min(res)) if len(res) >= 2 else 0.0)(
            _roll_med_residual(rec_r)[-72:]) if rpm else 0.0,
        "vib_temp_lagcorr": _lag_corr(vib, temp),
    }


def connect():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse="OEE_WH", database="OEE_DB", schema="ANALYTICS")


def embed(text: str) -> list[float]:
    """Fallback only: local bge-m3 (1024-dim) for Cortex-gated accounts.

    Not used on the production path — retrieval embeds the query in SQL via
    CORTEX.EMBED_TEXT_768 so it matches the 768-dim corpus.
    """
    r = requests.post(f"{OLLAMA_URL}/api/embed",
                      json={"model": "bge-m3", "input": text}, timeout=120)
    r.raise_for_status()
    return r.json()["embeddings"][0]


def ensure_table(cur):
    cur.execute("""
      CREATE TABLE IF NOT EXISTS OEE_DB.ANALYTICS.FINDING_ENRICHMENT (
        finding_id NUMBER PRIMARY KEY,
        asset_id VARCHAR(10),
        predicted_pattern VARCHAR(10),
        confidence FLOAT,
        probabilities VARCHAR(500),
        top_factors VARCHAR(500),
        similar_reports VARCHAR(4000),
        enriched_by VARCHAR(80) DEFAULT
          'xgboost registry-model + cortex EMBED_TEXT_768',
        enriched_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""")


def enrich_one(conn, model, classes, finding):
    cur = conn.cursor(snowflake.connector.DictCursor)
    fid, asset = finding["FINDING_ID"], finding["ASSET_ID"]

    feats = compute_features(conn.cursor(), asset)
    x = np.array([[feats[f] for f in FEATURES]])
    print(f"  features: " + ", ".join(f"{k}={v:.2f}" for k, v in feats.items()))

    proba = model.predict_proba(x)[0]
    top_i = int(np.argmax(proba))
    pred, conf = classes[top_i], float(proba[top_i])
    probs = {c: round(float(p), 3) for c, p in zip(classes, proba)}

    # SHAP: why
    try:
        import shap
        sv = shap.TreeExplainer(model).shap_values(x)
        contrib = np.abs(np.array(sv))[top_i][0] if np.array(sv).ndim == 3 \
            else np.abs(np.array(sv))[0]
        order = np.argsort(-contrib)[:3]
        factors = [{"feature": FEATURES[i], "value": round(float(x[0][i]), 3),
                    "weight": round(float(contrib[i]), 3)} for i in order]
    except Exception:
        factors = []

    # semantic history: similar past repairs — query embedded in-account by Cortex
    cur2 = conn.cursor()
    qtext = f"{finding['RCA_SUMMARY'][:400]}"
    cur2.execute(
        "SELECT r.report_id, r.fault_pattern_id, r.asset_id, "
        " ROUND(VECTOR_COSINE_SIMILARITY(e.embedding, "
        "   SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', %s)),3) score, "
        " r.diagnosis, r.parts_replaced, r.downtime_hours "
        "FROM OEE_DB.ANALYTICS.REPORT_EMBEDDINGS e "
        "JOIN OEE_DB.ANALYTICS.EXTRACTED_REPORTS r ON r.report_id=e.report_id "
        "ORDER BY score DESC LIMIT 3", (qtext,))
    sims = [{"report_id": r[0], "pattern": r[1], "asset": r[2], "score": float(r[3]),
             "remedy": (r[4] or "")[:180], "parts": (r[5] or "")[:80],
             "downtime_h": r[6]} for r in cur2.fetchall()]

    cur2.execute(
        "MERGE INTO OEE_DB.ANALYTICS.FINDING_ENRICHMENT t "
        "USING (SELECT %s AS finding_id) s ON t.finding_id=s.finding_id "
        "WHEN MATCHED THEN UPDATE SET predicted_pattern=%s, confidence=%s, "
        " probabilities=%s, top_factors=%s, similar_reports=%s, "
        " enriched_at=CURRENT_TIMESTAMP() "
        "WHEN NOT MATCHED THEN INSERT (finding_id, asset_id, predicted_pattern, "
        " confidence, probabilities, top_factors, similar_reports) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (fid, pred, conf, json.dumps(probs), json.dumps(factors), json.dumps(sims),
         fid, asset, pred, conf, json.dumps(probs), json.dumps(factors),
         json.dumps(sims)))
    conn.commit()
    print(f"finding {fid} ({asset}): {pred} conf={conf:.2f}, "
          f"{len(sims)} similar repairs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()

    model = xgb.XGBClassifier()
    model.load_model("data/fault_classifier.json")
    classes = json.load(open("data/fault_classes.json"))

    conn = connect()
    cur = conn.cursor(snowflake.connector.DictCursor)
    ensure_table(conn.cursor())
    while True:
        cur.execute("""
          SELECT f.finding_id, f.asset_id, f.rca_summary
          FROM OEE_DB.ANALYTICS.FINDINGS f
          LEFT JOIN OEE_DB.ANALYTICS.FINDING_ENRICHMENT e
            ON e.finding_id = f.finding_id
          WHERE e.finding_id IS NULL
            AND f.rca_summary NOT LIKE '[PENDING%'""")
        rows = cur.fetchall()
        for f in rows:
            try:
                enrich_one(conn, model, classes, f)
            except Exception as ex:
                print(f"finding {f['FINDING_ID']}: FAILED - {ex}")
        if not args.loop:
            break
        time.sleep(20)
    conn.close()


if __name__ == "__main__":
    main()
