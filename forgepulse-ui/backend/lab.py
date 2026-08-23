"""
lab.py — Anomaly Lab: inject a fault into a small segment of a synthetic
signal and let the REAL trained classifier find and name it.

Same physics and feature formulas as src/generate_training.py (kept in
sync); inference uses the exact model registered in the Model Registry
(data/fault_classifier.json copied into the image at build time).

Demonstrates discernment: the anomaly occupies only part of the window;
sliding-window classification localizes it and names the pattern.
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
from pathlib import Path

FEATURES = ["vib_z", "vib_slope", "vib_std_recent", "vib_ratio",
            "temp_z", "temp_slope", "vib_temp_lagcorr"]
CADENCE_MIN = 5
N = 72 * 60 // CADENCE_MIN          # 72h window, 864 samples

_MODEL = None
_CLASSES = None


def _load_model():
    global _MODEL, _CLASSES
    if _MODEL is None:
        import xgboost as xgb
        here = Path(__file__).resolve().parent
        _MODEL = xgb.XGBClassifier()
        _MODEL.load_model(str(here / "models" / "fault_classifier.json"))
        _CLASSES = json.load(open(here / "models" / "fault_classes.json"))
    return _MODEL, _CLASSES


# ── signal generation: normal base + fault inside [s0, s1) only ───────────
def generate(pattern: str, seed: int | None = None):
    rng = random.Random(seed)
    vb = rng.uniform(1.8, 3.6)
    tb = rng.uniform(58.0, 74.0)
    rb = rng.choice([850, 1450, 2950])
    ph1, ph2 = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
    rpm_swing = rng.uniform(0.04, 0.08)
    sev = rng.uniform(0.5, 1.0)
    # anomaly segment: 18-30% of the window, somewhere in the middle half
    seg_len = int(N * rng.uniform(0.18, 0.30))
    s0 = int(N * rng.uniform(0.25, 0.65 - seg_len / N))
    s1 = s0 + seg_len
    vib, temp, rpm = [], [], []
    stuck_val = None
    for i in range(N):
        shift = 1 + 0.02 * math.sin(2 * math.pi * i / 288)
        v = vb * shift + rng.gauss(0, vb * 0.05)
        t = tb * shift + rng.gauss(0, 0.8)
        r = rb * (1 + rpm_swing * math.sin(2 * math.pi * i / 72 + ph1)
                  + 0.02 * math.sin(2 * math.pi * i / 288 + ph2)) \
               * (1 + rng.gauss(0, 0.004))
        if s0 <= i < s1:
            g = (i - s0) / max(seg_len, 1)
            if pattern == "FP-01":
                v += vb * sev * (math.exp(2.2 * g) - 1) * 0.55
                t += 9 * sev * max(0.0, g - 0.15) / 0.85
            elif pattern == "FP-02":
                t += 11 * sev * g
            elif pattern == "FP-03":
                if stuck_val is None:
                    stuck_val = v
                v = stuck_val
            elif pattern == "FP-04":
                v += vb * 0.15 * sev * math.sin(i / 2.5)
                r += rb * 0.04 * sev * math.sin(i / 3.0)
                if i % 9 < 2:
                    r -= rb * 0.05 * sev * rng.uniform(0.6, 1)
        else:
            stuck_val = None
        vib.append(v); temp.append(t); rpm.append(r)
    return vib, temp, rpm, vb, tb, (s0, s1)


# ── feature formulas (window-local, mirrors training) ─────────────────────
def _slope_per_day(series):
    n = len(series)
    if n < 3:
        return 0.0
    xs = [i * CADENCE_MIN / 1440 for i in range(n)]
    mx, my = sum(xs) / n, sum(series) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, series))
    den = sum((x - mx) ** 2 for x in xs) or 1
    return num / den


def _lag_corr(a, b, lag=36):
    if len(a) <= lag + 2:
        return 0.0
    a2, b2 = a[:-lag], b[lag:]
    m = min(len(a2), len(b2)); a2, b2 = a2[:m], b2[:m]
    ma, mb = sum(a2) / m, sum(b2) / m
    num = sum((x - ma) * (y - mb) for x, y in zip(a2, b2))
    da = math.sqrt(sum((x - ma) ** 2 for x in a2))
    db = math.sqrt(sum((y - mb) ** 2 for y in b2))
    return num / (da * db) if da and db else 0.0


def _window_features(vib_w, temp_w, vb, tb):
    mad = st.median([abs(x - st.median(vib_w[:len(vib_w) // 3]))
                     for x in vib_w[:len(vib_w) // 3]]) or 0.01
    return {
        "vib_z": (st.mean(vib_w[-len(vib_w) // 3:]) - vb) / mad,
        "vib_slope": _slope_per_day(vib_w),
        "vib_std_recent": st.pstdev(vib_w[-72:]) if len(vib_w) >= 2 else 0.0,
        "vib_ratio": st.mean(vib_w[-len(vib_w) // 3:]) / vb,
        "temp_z": st.mean(temp_w[-len(temp_w) // 3:]) - tb,
        "temp_slope": _slope_per_day(temp_w),
        "vib_temp_lagcorr": _lag_corr(vib_w, temp_w),
    }


# ── sliding-window classification ─────────────────────────────────────────
def run_lab(pattern: str, seed: int | None = None) -> dict:
    import numpy as np
    model, classes = _load_model()
    vib, temp, rpm, vb, tb, (s0, s1) = generate(pattern, seed)

    WIN, STRIDE = 216, 36            # 18h windows, 3h stride
    detections = []
    for start in range(0, N - WIN + 1, STRIDE):
        end = start + WIN
        f = _window_features(vib[start:end], temp[start:end], vb, tb)
        x = np.array([[f[k] for k in FEATURES]])
        proba = model.predict_proba(x)[0]
        ci = int(np.argmax(proba))
        cls, conf = classes[ci], float(proba[ci])
        if cls != "NORMAL" and conf >= 0.5:
            detections.append({"start": start, "end": end,
                               "cls": cls, "conf": round(conf, 3)})
    # merge overlapping windows of the same class
    merged = []
    for d in detections:
        if merged and merged[-1]["cls"] == d["cls"] \
                and d["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = d["end"]
            merged[-1]["conf"] = max(merged[-1]["conf"], d["conf"])
        else:
            merged.append(dict(d))
    return {
        "pattern_injected": pattern,
        "injected_segment": {"start": s0, "end": s1},
        "n": N,
        "baseline_vib": round(vb, 2),
        "vib": [round(v, 3) for v in vib],
        "temp": [round(t, 2) for t in temp],
        "detections": merged,
        "model": "FAULT_PATTERN_CLASSIFIER (Model Registry) — sliding-window inference",
    }
