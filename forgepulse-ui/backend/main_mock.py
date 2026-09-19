"""
main_mock.py — ForgePulse local mock backend.

Serves the same API contract the SPCS FastAPI backend serves
(docs/spcs-deployment.md), but reads from the generator's CSVs in ../data
instead of Snowflake. The console developed against this runs unchanged
against the real backend — only the data source swaps.

Clean-clone safe: every dataset has a deterministic synthetic fallback, so
the module imports and the full API contract is exercisable with no data/
directory present (the generator's CSVs are gitignored). Fallback data is
shaped to match the real generator: 12 assets across 3 lines, AST-007
degrading into a bearing fault, 35 days of history so the 31-to-3-day
baseline window is populated.

Run:  uvicorn main_mock:app --reload --port 8000   (from backend/, venv active)
Deps: fastapi uvicorn pandas numpy
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

SENSORS = ["VIBRATION_RMS", "BEARING_TEMP", "RPM", "CURRENT_DRAW"]
_BASES = {"VIBRATION_RMS": 3.1, "BEARING_TEMP": 68.0,
          "RPM": 1450.0, "CURRENT_DRAW": 38.0}
FAULT_ASSET = "AST-007"


# ── synthetic fallbacks (deterministic; used only when data/ is absent) ──────
def _synth_telemetry() -> pd.DataFrame:
    """12 assets x 4 sensors x 35 days at hourly cadence.

    35 days so the 31-to-3-day baseline window has rows. AST-007 ramps over
    the final 5 days on vibration and bearing temperature, ending well above
    its own baseline so health_score() drives it critical — the same event
    the real pipeline detects.
    """
    import numpy as np
    rng = np.random.default_rng(42)
    hours = 35 * 24
    t0 = pd.Timestamp("2026-08-01")
    rows = []
    for a in range(1, 13):
        aid = f"AST-{a:03d}"
        faulty = aid == FAULT_ASSET
        for sensor in SENSORS:
            base = _BASES[sensor]
            for i in range(hours):
                v = base * (1 + 0.02 * np.sin(i / 24)) + rng.normal(0, base * 0.03)
                if faulty and sensor in ("VIBRATION_RMS", "BEARING_TEMP"):
                    ramp_start = hours - 5 * 24
                    if i >= ramp_start:
                        frac = (i - ramp_start) / (5 * 24)
                        v *= 1.0 + 2.6 * frac
                rows.append({"asset_id": aid, "sensor_type": sensor,
                             "ts": t0 + pd.Timedelta(hours=i),
                             "value": round(float(v), 3),
                             "quality_flag": "GOOD"})
    return pd.DataFrame(rows)


def _synth_assets() -> pd.DataFrame:
    names = ["Main Drive Motor", "Conveyor Gearbox", "Hydraulic Pump",
             "Air Compressor"]
    types = ["MOTOR", "GEARBOX", "PUMP", "COMPRESSOR"]
    rows = []
    for a in range(1, 13):
        line = f"L{(a - 1) // 4 + 1}"
        k = (a - 1) % 4
        rows.append({
            "asset_id": f"AST-{a:03d}",
            "asset_name": f"{line}{names[k]}",
            "asset_type": types[k],
            "line_id": line,
            "model_no": f"MDL-{1000 + a}",
            "install_date": "2019-03-12",
            "criticality": "HIGH" if a % 3 == 1 or a == 7 else "MEDIUM",
        })
    return pd.DataFrame(rows)


def _synth_wos(now: pd.Timestamp) -> pd.DataFrame:
    """A small fleet work-order history, including the two bearing jobs the
    RCA layer cites, so /api/workorders and the history panel have content."""
    seed = [
        ("WO-24101", "AST-003", "BEARING_WEAR", 9.5,
         "Comp tripped on high vib alarm. 6312 brg cage broken, rollers "
         "pitted. Replaced DE+NDE brgs, regreased. Suspect grease "
         "contamination - PM interval should be reduced.",
         "BRG-6312-2RS x2, GRS-EP2 grease", 74),
        ("WO-24290", "AST-009", "BEARING_WEAR", 12.0,
         "End of bearing life, ~14 months duty. Monitoring gap - no rounds "
         "logged for 6 weeks. Replaced NDE bearing, aligned to 0.03mm.",
         "BRG-6316-C3 x2", 45),
        ("WO-24312", "AST-002", "COOLING_DEGRADATION", 4.0,
         "Cooler fins fouled, dP across cooler high. Cleaned, restored "
         "delta-T to spec.", "FLT-AIR-STD", 30),
        ("WO-24355", "AST-008", "SENSOR_FAULT", 1.0,
         "Vibration transmitter mount stud failed - fatigue. Signal frozen. "
         "Replaced stud and re-torqued. No machine fault found.",
         "TX-VIB-100mV", 18),
        ("WO-24390", "AST-011", "BELT_SLIP_RPM", 3.0,
         "Drive belt glazed, speed hunting under load. Replaced belt set, "
         "re-tensioned.", "BLT-SPZ-1400 x3", 9),
    ]
    rows = []
    for wo_id, aid, mode, hrs, notes, parts, days_ago in seed:
        opened = now - pd.Timedelta(days=days_ago)
        rows.append({
            "wo_id": wo_id, "asset_id": aid, "wo_type": "CORRECTIVE",
            "opened_ts": opened,
            "closed_ts": opened + pd.Timedelta(hours=hrs),
            "failure_mode": mode, "technician_notes": notes,
            "parts_used": parts, "downtime_hours": hrs,
        })
    return pd.DataFrame(rows)


def _synth_schedule(now: pd.Timestamp) -> pd.DataFrame:
    """30 days x 3 lines x 2 shifts, ending at NOW, so the OEE endpoint's
    trailing-7-day window is populated."""
    import numpy as np
    rng = np.random.default_rng(7)
    rows = []
    for d in range(30, -1, -1):
        day = (now - pd.Timedelta(days=d)).normalize()
        for line in ("L1", "L2", "L3"):
            for shift in (1, 2):
                planned = 960
                actual = int(planned * rng.uniform(0.90, 0.99))
                good = int(actual * rng.uniform(0.975, 0.998))
                rows.append({
                    "line_id": line, "shift_date": day, "shift_no": shift,
                    "planned_minutes": 480, "planned_units": planned,
                    "actual_units": actual, "good_units": good,
                })
    return pd.DataFrame(rows)


# ── load once at startup (CSV if present, synthetic otherwise) ──────────────
try:
    telemetry = pd.read_csv(DATA / "raw_telemetry.csv", parse_dates=["ts"])
except Exception:
    telemetry = _synth_telemetry()

NOW = telemetry.ts.max()

try:
    assets = pd.read_csv(DATA / "asset_master.csv")
except Exception:
    assets = _synth_assets()

try:
    wos = pd.read_csv(DATA / "work_order_history.csv",
                      parse_dates=["opened_ts", "closed_ts"])
except Exception:
    wos = _synth_wos(NOW)

try:
    schedule = pd.read_csv(DATA / "production_schedule.csv",
                           parse_dates=["shift_date"])
except Exception:
    schedule = _synth_schedule(NOW)

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
# The deployed backend reads the RAW_TELEMETRY tail instead — same shape.
import math
import random
import time as _time

_BASE = {r.asset_id: {s: None for s in SENSORS} for _, r in assets.iterrows()}
for _sensor in SENSORS:
    s = telemetry[telemetry.sensor_type == _sensor]
    med = (s[(s.ts >= BASELINE_WINDOW[0]) & (s.ts <= BASELINE_WINDOW[1])]
           .groupby("asset_id").value.median())
    cur = s[s.ts > NOW - timedelta(hours=2)].groupby("asset_id").value.mean()
    for aid in _BASE:
        fallback = float(med.get(aid, _BASES[_sensor]))
        _BASE[aid][_sensor] = {"base": fallback,
                               "now": float(cur.get(aid, fallback))}

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


# ── serve the console ───────────────────────────────────────────────────────
from fastapi.responses import FileResponse

_WEB = Path(__file__).resolve().parent.parent / "web"


@app.get("/")
def console():
    return FileResponse(_WEB / "console.html")
