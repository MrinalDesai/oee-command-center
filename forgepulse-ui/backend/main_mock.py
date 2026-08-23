"""
main.py — ForgePulse local mock backend.

Serves the same API contract the SPCS FastAPI backend will serve in G4
(docs/spcs-deployment.md), but reads from the generator's CSVs in ../data
instead of Snowflake. The frontend developed against this runs unchanged
against the real backend later — only the data source swaps.

Run:  uvicorn main:app --reload --port 8000   (from backend/, venv active)
Deps: fastapi uvicorn pandas
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

DATA = Path(__file__).resolve().parent.parent.parent / "data"

app = FastAPI(title="ForgePulse mock API")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ── load once at startup ────────────────────────────────────────────────────
def _synth_telemetry():
    """Deterministic in-memory telemetry so the mock runs from a clean clone
    (no data/ needed). 12 assets x 4 sensors x 6h at 5-min cadence."""
    import numpy as np
    rng = np.random.default_rng(42)
    rows = []
    t0 = pd.Timestamp("2026-08-01")
    bases = {"VIBRATION_RMS": 2.6, "BEARING_TEMP": 66.0, "RPM": 1450.0,
             "CURRENT_A": 38.0}
    for a in range(1, 13):
        aid = f"AST-{a:03d}"
        fault = aid == "AST-007"
        for s_i, (sensor, base) in enumerate(bases.items()):
            for i in range(72):
                v = base * (1 + 0.02 * np.sin(i / 12)) \
                    + rng.normal(0, base * 0.03)
                if fault and sensor in ("VIBRATION_RMS", "BEARING_TEMP"):
                    v += base * 1.5 * (i / 72)
                rows.append({"asset_id": aid, "sensor_type": sensor,
                             "ts": t0 + pd.Timedelta(minutes=5 * i),
                             "value": v, "quality_flag": "GOOD"})
    return pd.DataFrame(rows)


try:
    telemetry = pd.read_csv(DATA / "raw_telemetry.csv", parse_dates=["ts"])
except Exception:
    telemetry = _synth_telemetry()
assets = pd.read_csv(DATA / "asset_master.csv")
wos = pd.read_csv(DATA / "work_order_history.csv", parse_dates=["opened_ts", "closed_ts"])
schedule = pd.read_csv(DATA / "production_schedule.csv", parse_dates=["shift_date"])

NOW = telemetry.ts.max()
BASELINE_WINDOW = (NOW - timedelta(days=31), NOW - timedelta(days=3))

vib = telemetry[telemetry.sensor_type == "VIBRATION_RMS"]
_base = (vib[(vib.ts >= BASELINE_WINDOW[0]) & (vib.ts <= BASELINE_WINDOW[1])]
         .groupby("asset_id").value.median())
_recent = vib[vib.ts > NOW - timedelta(hours=24)].groupby("asset_id").value.mean()


def health_score(aid: str) -> float:
    """1.0 healthy .. 0.0 critical, from recent vibration vs baseline."""
    base, recent = _base.get(aid), _recent.get(aid)
    if base is None or recent is None:
        return 1.0
    ratio = recent / base
    return round(max(0.0, min(1.0, 1.0 - (ratio - 1.0) / 2.5)), 2)


def status_of(score: float) -> str:
    if score < 0.35:
        return "critical"
    if score < 0.7:
        return "watch"
    return "healthy"


# ── endpoints (contract per docs/spcs-deployment.md) ────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "healthy", "data_through": str(NOW)}


@app.get("/api/assets")
def get_assets() -> list[dict]:
    out = []
    for _, a in assets.iterrows():
        score = health_score(a.asset_id)
        out.append({
            "asset_id": a.asset_id, "name": a.asset_name,
            "type": a.asset_type, "line": a.line_id,
            "criticality": a.criticality,
            "health": score, "status": status_of(score),
        })
    return out


@app.get("/api/telemetry/{asset_id}")
def get_telemetry(asset_id: str, sensor: str = "VIBRATION_RMS",
                  hours: int = 24) -> dict:
    df = telemetry[(telemetry.asset_id == asset_id)
                   & (telemetry.sensor_type == sensor)
                   & (telemetry.ts > NOW - timedelta(hours=hours))]
    if df.empty:
        raise HTTPException(404, f"No telemetry for {asset_id}/{sensor}")
    # downsample to <=200 points for sparklines/charts
    step = max(1, len(df) // 200)
    pts = df.iloc[::step]
    return {
        "asset_id": asset_id, "sensor": sensor,
        "baseline": float(_base.get(asset_id, 0)) if sensor == "VIBRATION_RMS" else None,
        "points": [{"ts": str(r.ts), "value": float(r.value)}
                   for r in pts.itertuples()],
    }


@app.get("/api/alerts")
def get_alerts() -> list[dict]:
    """Mock mirror of ANALYTICS.ANOMALY_EVENTS: derive live from data so the
    frontend sees the same AST-007 event the real pipeline found."""
    out = []
    for _, a in assets.iterrows():
        score = health_score(a.asset_id)
        if score < 0.5:
            out.append({
                "event_id": len(out) + 1, "asset_id": a.asset_id,
                "probable_mode": "BEARING_WEAR",
                "severity": "HIGH" if a.criticality == "HIGH" else "MEDIUM",
                "score": round(1 - score, 2), "status": "ACTIONED",
                "detected_ts": str(NOW),
                "days_to_threshold": 0,
            })
    return out


@app.get("/api/oee")
def get_oee() -> list[dict]:
    out = []
    recent = schedule[schedule.shift_date > NOW - timedelta(days=7)]
    for line, g in recent.groupby("line_id"):
        avail = g.actual_units.sum() / max(g.planned_units.sum(), 1)
        quality = g.good_units.sum() / max(g.actual_units.sum(), 1)
        perf = 0.94  # generator folds performance into actuals; fixed proxy
        out.append({
            "line": line,
            "availability": round(min(avail / perf, 1.0), 3),
            "performance": perf,
            "quality": round(quality, 3),
            "oee": round(avail * quality, 3),
        })
    return out


@app.get("/api/workorders")
def get_workorders() -> list[dict]:
    recent = wos.sort_values("opened_ts", ascending=False).head(20)
    return [{
        "wo_id": r.wo_id, "asset_id": r.asset_id, "type": r.wo_type,
        "opened": str(r.opened_ts), "failure_mode": r.failure_mode
        if isinstance(r.failure_mode, str) else None,
        "downtime_hours": float(r.downtime_hours),
        "notes": r.technician_notes,
    } for r in recent.itertuples()]


# ── live feed (Sentinel-style monitor) ──────────────────────────────────────
# Synthesizes a rolling live window per asset/sensor, mirroring the Kafka
# producer's physics (baseline noise; AST-007 rides its ramp with bursts).
# In G4 this endpoint reads the RAW_TELEMETRY tail instead — same shape.
import math
import random
import time as _time

_BASE = {r.asset_id: dict(VIBRATION_RMS=None, BEARING_TEMP=None, RPM=None,
                          CURRENT_DRAW=None) for _, r in assets.iterrows()}
for _sensor in ["VIBRATION_RMS", "BEARING_TEMP", "RPM", "CURRENT_DRAW"]:
    s = telemetry[telemetry.sensor_type == _sensor]
    med = (s[(s.ts >= BASELINE_WINDOW[0]) & (s.ts <= BASELINE_WINDOW[1])]
           .groupby("asset_id").value.median())
    cur = s[s.ts > NOW - timedelta(hours=2)].groupby("asset_id").value.mean()
    for aid in _BASE:
        _BASE[aid][_sensor] = {"base": float(med.get(aid, 0)),
                               "now": float(cur.get(aid, med.get(aid, 0)))}

NOISE = {"VIBRATION_RMS": 0.10, "BEARING_TEMP": 0.012,
         "RPM": 0.004, "CURRENT_DRAW": 0.03}


@app.get("/api/live/{asset_id}")
def get_live(asset_id: str, sensor: str = "VIBRATION_RMS",
             seconds: int = 600) -> dict:
    b = _BASE.get(asset_id, {}).get(sensor)
    if not b:
        raise HTTPException(404, f"{asset_id}/{sensor}")
    level, base = b["now"], b["base"]
    degraded = level > base * 1.6 and sensor in ("VIBRATION_RMS", "BEARING_TEMP")
    # RPM fault demo: AST-004 conveyor shows belt-slip hunting (speed oscillation)
    rpm_fault = (asset_id == "AST-004" and sensor == "RPM")
    t0 = int(_time.time()) - seconds
    rng = random.Random(asset_id + sensor + str(t0 // 30))  # stable per 30s
    pts, anomaly = [], []
    burst_at = rng.randrange(seconds // 3, 2 * seconds // 3) if degraded else -1
    for i in range(seconds):
        v = level * (1 + math.sin(i / 47) * 0.01) + rng.gauss(0, NOISE[sensor] * base)
        if degraded and burst_at <= i < burst_at + 90:
            v += level * 0.8 * math.sin((i - burst_at) / 3) * rng.uniform(0.5, 1)
        if rpm_fault and i >= seconds // 2:
            # hunting: +-4% slow oscillation with slip dips
            v += base * 0.04 * math.sin(i / 6)
            if i % 45 < 6:
                v -= base * 0.06 * rng.uniform(0.6, 1)   # slip dip
        pts.append(round(v, 3))
    if rpm_fault:
        anomaly.append({"start": seconds // 2, "end": seconds,
                        "label": "RPM INSTABILITY - BELT SLIP PATTERN"})
    elif burst_at >= 0:
        anomaly.append({"start": burst_at, "end": burst_at + 90,
                        "label": "ABNORMAL PATTERN DETECTED"})
    vals = pts
    return {
        "asset_id": asset_id, "sensor": sensor, "t0": t0, "hz": 1,
        "baseline": base, "points": pts, "anomaly": anomaly,
        "stats": {"rms": round((sum(v * v for v in vals) / len(vals)) ** 0.5, 2),
                  "peak": round(max(vals), 2),
                  "avg": round(sum(vals) / len(vals), 2)},
    }


# ── serve the SentinelDesk-style console ────────────────────────────────────
from fastapi.responses import FileResponse

_WEB = Path(__file__).resolve().parent.parent / "web"

@app.get("/")
def console():
    return FileResponse(_WEB / "console.html")
