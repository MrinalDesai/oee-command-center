"""
generate_training.py — Labeled training corpus for the fault classifier.

Simulates windowed sensor episodes with the same physics as the live
generator/producer, computes the SAME engineered features the detection
layer uses, and emits a labeled dataset:

    NORMAL, FP-01 (bearing wear), FP-02 (cooling), FP-03 (stuck sensor),
    FP-04 (belt slip / rpm hunting)

Deterministic (seeded). 50 episodes per class by default = 250 rows.

Usage:  python src/generate_training.py [--per-class 50] [--out data/training.csv]
"""
from __future__ import annotations

import argparse
import csv
import math
import random

import statistics as st

CLASSES = ["NORMAL", "FP-01", "FP-02", "FP-03", "FP-04"]

# per-sensor plausible baselines (drawn per episode)
BASE = {
    "vib": (1.8, 3.6),      # mm/s RMS
    "temp": (58.0, 74.0),   # C
    "rpm": (850, 2950),
    "amp": (18.0, 60.0),    # A
}

WINDOW_H = 72               # hours simulated
CADENCE_MIN = 5             # one reading / 5 min
N = WINDOW_H * 60 // CADENCE_MIN


def simulate(cls: str, rng: random.Random):
    vb = rng.uniform(*BASE["vib"]); tb = rng.uniform(*BASE["temp"])
    rb = rng.choice([850, 1450, 2950]); ab = rng.uniform(*BASE["amp"])
    vib, temp, rpm = [], [], []
    # degradation can begin inside the window OR long before it (saturated case)
    ramp_start = rng.uniform(-0.8, 0.5) * N      # negative = already-degraded window
    ph1, ph2 = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
    rpm_swing = rng.uniform(0.04, 0.08)          # intraday speed variation (real plants)
    sev = rng.uniform(0.25, 1.1)                 # calibrated to the live generator's fault intensity
    stuck_val = None
    for i in range(N):
        shift = 1 + 0.02 * math.sin(2 * math.pi * i / (24 * 12))
        v = vb * shift + rng.gauss(0, vb * 0.05)
        t = tb * shift + rng.gauss(0, 0.8)
        r = rb * (1 + rpm_swing * math.sin(2 * math.pi * i / 72 + ph1)
                  + 0.02 * math.sin(2 * math.pi * i / 288 + ph2)) \
               * (1 + rng.gauss(0, 0.004))       # production-schedule speed swings, like the real data
        if cls == "FP-01" and i > ramp_start:
            g = min(1.2, (i - ramp_start) / max(N - ramp_start, N * 0.5))
            v += vb * sev * (math.exp(2.2 * g) - 1) * 0.55
            t += 9 * sev * max(0.0, g - 0.15) / 0.85       # lagged follow
        elif cls == "FP-02" and i > ramp_start:
            g = min(1.2, (i - ramp_start) / max(N - ramp_start, N * 0.5))
            t += 11 * sev * g                              # temp only
        elif cls == "FP-03" and i > ramp_start:
            if stuck_val is None:
                stuck_val = v
            v = stuck_val                                  # frozen signal
        elif cls == "FP-04" and i > ramp_start:
            v += vb * 0.15 * sev * math.sin(i / 2.5)
            r += rb * 0.04 * sev * math.sin(i / 3.0)
            if i % 9 < 2:
                r -= rb * 0.05 * sev * rng.uniform(0.6, 1)  # slip dips
        vib.append(v); temp.append(t); rpm.append(r)
    return vib, temp, rpm, vb, tb, rb



def _roll_med_residual(series, k=12):
    if len(series) < k + 2:
        return [0.0] * len(series)
    import statistics as _st
    out = []
    for i in range(len(series)):
        lo = max(0, i - k)
        out.append(series[i] - _st.median(series[lo:i + 1]))
    return out


def slope_per_day(series, cadence_min=CADENCE_MIN):
    n = len(series)
    xs = [i * cadence_min / 1440 for i in range(n)]
    mx, my = sum(xs) / n, sum(series) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, series))
    den = sum((x - mx) ** 2 for x in xs) or 1
    return num / den


def lag_corr(a, b, lag=36):     # 3h lag at 5-min cadence
    a2, b2 = a[:-lag], b[lag:]
    ma, mb = sum(a2) / len(a2), sum(b2) / len(b2)
    num = sum((x - ma) * (y - mb) for x, y in zip(a2, b2))
    da = math.sqrt(sum((x - ma) ** 2 for x in a2))
    db = math.sqrt(sum((y - mb) ** 2 for y in b2))
    return num / (da * db) if da and db else 0.0


def features(vib, temp, rpm, vb, tb, rb) -> dict:
    recent_v, recent_t, recent_r = vib[-288:], temp[-288:], rpm[-288:]
    mad_v = st.median([abs(x - st.median(vib[:N // 3])) for x in vib[:N // 3]]) or 0.01
    return {
        "vib_z": (st.mean(recent_v) - vb) / mad_v,
        "vib_slope": slope_per_day(vib[-864:]),
        "vib_std_recent": st.pstdev(recent_v[-72:]),
        "vib_ratio": st.mean(recent_v) / vb,
        "temp_z": (st.mean(recent_t) - tb) / 1.0,
        "temp_slope": slope_per_day(temp[-864:]),
        "rpm_cv": st.pstdev(_roll_med_residual(recent_r)) / st.mean(recent_r),
        "rpm_osc": (lambda res: max(res) - min(res))(_roll_med_residual(recent_r)[-72:]),
        "vib_temp_lagcorr": lag_corr(vib[-864:], temp[-864:]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=50)
    ap.add_argument("--out", default="data/training.csv")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    rows = []
    for cls in CLASSES:
        for _ in range(args.per_class):
            vib, temp, rpm, vb, tb, rb = simulate(cls, rng)
            f = features(vib, temp, rpm, vb, tb, rb)
            f["label"] = cls
            rows.append(f)
    rng.shuffle(rows)

    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} labeled episodes -> {args.out}")
    for c in CLASSES:
        print(f"  {c}: {sum(1 for r in rows if r['label'] == c)}")


if __name__ == "__main__":
    main()
