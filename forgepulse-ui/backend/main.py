"""
main.py — ForgePulse console backend, Snowflake-backed.

Same API contract as main_mock.py, but every endpoint reads the live
Snowflake account: health from RAW_TELEMETRY, alerts from ANOMALY_EVENTS
(with fault_pattern_id), work orders from WORK_ORDERS_GENERATED, findings
and extracted reports included. The live feed reads the Kafka-fed
telemetry tail.

Auth resolves in order:
  1. SPCS service token (/snowflake/session/token) — deployed mode
  2. SNOWFLAKE_ACCOUNT/USER/PASSWORD env vars     — local dev

Run local:  . .\\scripts\\env.ps1 ; cd forgepulse-ui\\backend ;
            uvicorn main:app --reload --port 8000
Mock mode:  uvicorn main_mock:app --port 8000   (no Snowflake needed)
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import snowflake.connector
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="ForgePulse API (Snowflake)")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

_WEB = Path(__file__).resolve().parent.parent / "web"
_conn = None


def conn():
    global _conn
    if _conn is not None:
        try:
            _conn.cursor().execute("SELECT 1")
            return _conn
        except Exception:
            _conn = None
    token_path = Path("/snowflake/session/token")
    if token_path.exists():  # SPCS
        _conn = snowflake.connector.connect(
            host=os.environ["SNOWFLAKE_HOST"],
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            token=token_path.read_text(),
            authenticator="oauth",
            warehouse="OEE_WH", database="OEE_DB", schema="ANALYTICS")
    else:  # local dev
        _conn = snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            warehouse="OEE_WH", database="OEE_DB", schema="ANALYTICS")
    return _conn


def q(sql: str, params=None) -> list[dict]:
    cur = conn().cursor(snowflake.connector.DictCursor)
    cur.execute(sql, params or ())
    return cur.fetchall()


# ── tiny TTL cache (protect the XS warehouse from poll storms) ─────────────
_cache: dict[str, tuple[float, object]] = {}

def cached(key: str, ttl: float, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


# ── endpoints ──────────────────────────────────────────────────────────────

@app.get("/")
def console():
    return FileResponse(_WEB / "console.html")


@app.get("/health")
def health():
    return {"status": "healthy", "backend": "snowflake"}


def _assets_live():
    rows = q("""
        WITH bounds AS (SELECT MAX(ts) AS now_ts FROM OEE_DB.OT.RAW_TELEMETRY),
        base AS (
          SELECT asset_id, MEDIAN(value) AS b
          FROM OEE_DB.OT.RAW_TELEMETRY, bounds
          WHERE sensor_type='VIBRATION_RMS' AND quality_flag='GOOD'
            AND ts BETWEEN DATEADD(day,-31,now_ts) AND DATEADD(day,-3,now_ts)
          GROUP BY asset_id),
        rec AS (
          SELECT asset_id, AVG(value) AS r
          FROM OEE_DB.OT.RAW_TELEMETRY, bounds
          WHERE sensor_type='VIBRATION_RMS' AND ts > DATEADD(hour,-24,now_ts)
          GROUP BY asset_id),
        ev AS (
          SELECT asset_id, MAX(probable_mode) AS mode
          FROM OEE_DB.ANALYTICS.ANOMALY_EVENTS
          WHERE status IN ('NEW','INVESTIGATING','ACTIONED')
          GROUP BY asset_id)
        SELECT am.asset_id, am.asset_name, am.asset_type, am.line_id,
               am.criticality, base.b, rec.r, ev.mode
        FROM OEE_DB.ERP.ASSET_MASTER am
        LEFT JOIN base ON base.asset_id = am.asset_id
        LEFT JOIN rec  ON rec.asset_id  = am.asset_id
        LEFT JOIN ev   ON ev.asset_id   = am.asset_id
        ORDER BY am.asset_id""")
    out = []
    for r in rows:
        b, rc = float(r["B"] or 0), float(r["R"] or 0)
        ratio = (rc / b) if b else 1.0
        score = round(max(0.0, min(1.0, 1.0 - (ratio - 1.0) / 2.5)), 2)
        status = ("sensor-fault" if r["MODE"] == "SENSOR_FAULT"
                  else "critical" if score < 0.35
                  else "watch" if score < 0.7 else "healthy")
        out.append({"asset_id": r["ASSET_ID"], "name": r["ASSET_NAME"],
                    "type": r["ASSET_TYPE"], "line": r["LINE_ID"],
                    "criticality": r["CRITICALITY"],
                    "health": score, "status": status})
    return out


@app.get("/api/assets")
def get_assets():
    return cached("assets", 30, _assets_live)


@app.get("/api/telemetry/{asset_id}")
def get_telemetry(asset_id: str, sensor: str = "VIBRATION_RMS", hours: int = 24):
    rows = q("""
        SELECT ts, value FROM OEE_DB.OT.RAW_TELEMETRY
        WHERE asset_id=%s AND sensor_type=%s
          AND ts > DATEADD(hour, -%s, (SELECT MAX(ts) FROM OEE_DB.OT.RAW_TELEMETRY))
        ORDER BY ts""", (asset_id, sensor, hours))
    if not rows:
        raise HTTPException(404, f"no telemetry {asset_id}/{sensor}")
    step = max(1, len(rows) // 200)
    return {"asset_id": asset_id, "sensor": sensor, "baseline": None,
            "points": [{"ts": str(r["TS"]), "value": float(r["VALUE"])}
                       for r in rows[::step]]}


@app.get("/api/alerts")
def get_alerts():
    def _f():
        rows = q("""
            SELECT event_id, asset_id, probable_mode, fault_pattern_id,
                   severity, score, status, detected_ts, days_to_threshold
            FROM OEE_DB.ANALYTICS.ANOMALY_EVENTS
            WHERE status <> 'DISMISSED' ORDER BY detected_ts DESC""")
        return [{"event_id": r["EVENT_ID"], "asset_id": r["ASSET_ID"],
                 "probable_mode": r["PROBABLE_MODE"],
                 "fault_pattern_id": r["FAULT_PATTERN_ID"],
                 "severity": r["SEVERITY"], "score": float(r["SCORE"] or 0),
                 "status": r["STATUS"], "detected_ts": str(r["DETECTED_TS"]),
                 "days_to_threshold": r["DAYS_TO_THRESHOLD"]} for r in rows]
    return cached("alerts", 15, _f)


@app.get("/api/oee")
def get_oee():
    def _f():
        rows = q("""
            SELECT line_id, SUM(actual_units) a, SUM(planned_units) p,
                   SUM(good_units) g
            FROM OEE_DB.ERP.PRODUCTION_SCHEDULE
            WHERE shift_date > DATEADD(day,-7,CURRENT_DATE())
            GROUP BY line_id ORDER BY line_id""")
        perf = 0.94
        out = []
        for r in rows:
            avail = min(float(r["A"]) / max(float(r["P"]), 1) / perf, 1.0)
            qual = float(r["G"]) / max(float(r["A"]), 1)
            out.append({"line": r["LINE_ID"], "availability": round(avail, 3),
                        "performance": perf, "quality": round(qual, 3),
                        "oee": round(avail * perf * qual, 3), "impact": None})
        # impact bridge: for each line with an open event, avoided-downtime math
        evs = q("""
            SELECT e.asset_id, e.probable_mode, am.line_id
            FROM OEE_DB.ANALYTICS.ANOMALY_EVENTS e
            JOIN OEE_DB.ERP.ASSET_MASTER am ON am.asset_id=e.asset_id
            WHERE e.status IN ('NEW','INVESTIGATING','ACTIONED')""")
        PLANNED_H = 4.0
        WEEK_H = 7 * 24.0
        for ev in evs:
            try:
                h = q("""SELECT AVG(downtime_hours) d, COUNT(*) n
                         FROM OEE_DB.ERP.WORK_ORDER_HISTORY
                         WHERE failure_mode = %s""", (ev["PROBABLE_MODE"],))
                unplanned = float(h[0]["D"] or 10.0)
                n_hist = int(h[0]["N"] or 0)
            except Exception:
                unplanned, n_hist = 10.0, 0
            avoided = max(unplanned - PLANNED_H, 0.0)
            for o in out:
                if o["line"] == ev["LINE_ID"]:
                    d_av = avoided / WEEK_H
                    new_av = min(o["availability"] + d_av, 1.0)
                    o["impact"] = {
                        "asset": ev["ASSET_ID"],
                        "mode": ev["PROBABLE_MODE"],
                        "avg_unplanned_h": round(unplanned, 1),
                        "history_n": n_hist,
                        "planned_h": PLANNED_H,
                        "avoided_h": round(avoided, 1),
                        "projected_availability": round(new_av, 3),
                        "projected_oee": round(new_av * o["performance"] * o["quality"], 3)}
        return out
    return cached("oee", 120, _f)


@app.get("/api/workorders")
def get_workorders():
    rows = q("""
        SELECT wo_id, asset_id, tier, priority, status, parts_availability,
               scheduled_for, description, suggested_parts
        FROM OEE_DB.ANALYTICS.WORK_ORDERS_GENERATED ORDER BY wo_id""")
    return [{"wo_id": r["WO_ID"], "asset_id": r["ASSET_ID"], "tier": r["TIER"],
             "type": "PREDICTIVE", "opened": str(r["SCHEDULED_FOR"]),
             "failure_mode": None, "downtime_hours": 0,
             "status": r["STATUS"], "parts": r["SUGGESTED_PARTS"],
             "notes": r["DESCRIPTION"]} for r in rows]


@app.get("/api/findings/{asset_id}")
def get_finding(asset_id: str):
    rows = q("""
        SELECT f.finding_id, f.rca_summary, f.recommended_action,
               e.fault_pattern_id, e.severity
        FROM OEE_DB.ANALYTICS.FINDINGS f
        JOIN OEE_DB.ANALYTICS.ANOMALY_EVENTS e ON e.event_id=f.event_id
        WHERE f.asset_id=%s ORDER BY f.finding_id DESC LIMIT 1""", (asset_id,))
    if not rows:
        raise HTTPException(404, "no finding")
    r = rows[0]
    return {"finding_id": r["FINDING_ID"], "rca_summary": r["RCA_SUMMARY"],
            "recommended_action": r["RECOMMENDED_ACTION"],
            "fault_pattern_id": r["FAULT_PATTERN_ID"], "severity": r["SEVERITY"]}


@app.get("/api/reports/{asset_id}")
def get_reports(asset_id: str):
    rows = q("""
        SELECT report_id, fault_pattern_id, failure_date, symptoms, diagnosis,
               parts_replaced, technician
        FROM OEE_DB.ANALYTICS.EXTRACTED_REPORTS
        WHERE asset_id=%s ORDER BY report_id""", (asset_id,))
    return [{k.lower(): (str(v) if v is not None else "") for k, v in r.items()}
            for r in rows]


@app.get("/api/parts/{asset_id}")
def api_parts(asset_id: str):
    wo = q("""
        SELECT wo_id, suggested_parts FROM OEE_DB.ANALYTICS.WORK_ORDERS_GENERATED
        WHERE asset_id=%s AND status='OPEN' ORDER BY wo_id DESC LIMIT 1""",
        (asset_id,))
    if not wo or not wo[0]["SUGGESTED_PARTS"]:
        raise HTTPException(404, "no open work order / parts")
    parts = [p.strip() for p in wo[0]["SUGGESTED_PARTS"].split(",") if p.strip()]
    placeholders = ",".join(["%s"] * len(parts))
    inv = []
    for col in ("PART_NO", "PART_ID"):
        try:
            inv = q(f"SELECT * FROM OEE_DB.ERP.SPARE_PARTS_INVENTORY "
                    f"WHERE {col} IN ({placeholders})", tuple(parts))
            if inv:
                break
        except Exception:
            continue
    by_key = {}
    for r in inv:
        key = r.get("PART_NO") or r.get("PART_ID")
        by_key[str(key)] = {k.lower(): ("" if v is None else str(v))
                            for k, v in r.items()}
    out = []
    for p in parts:
        row = by_key.get(p, {})
        qty = None
        for cand in ("qty_on_hand", "stock_qty", "quantity", "qty"):
            if cand in row:
                qty = row[cand]
                break
        out.append({"part": p, "found": bool(row), "qty": qty, "detail": row})
    return {"wo_id": wo[0]["WO_ID"], "parts": out}


@app.get("/api/history/{pattern}")
def api_history(pattern: str):
    rows = q("""
        SELECT report_id, asset_id, model_no, failure_date, symptoms,
               diagnosis, parts_replaced, downtime_hours, technician
        FROM OEE_DB.ANALYTICS.EXTRACTED_REPORTS
        WHERE fault_pattern_id = %s ORDER BY report_id""", (pattern,))
    return [{k.lower(): ("" if v is None else str(v)) for k, v in r.items()}
            for r in rows]


@app.get("/api/lab/{pattern}")
def api_lab(pattern: str, seed: int = None):
    if pattern not in ("FP-01", "FP-02", "FP-03", "FP-04"):
        raise HTTPException(400, "pattern must be FP-01..FP-04")
    import lab
    try:
        return lab.run_lab(pattern, seed)
    except Exception as e:
        raise HTTPException(500, f"lab error: {e}")


@app.get("/api/diagnosis/{asset_id}")
def get_diagnosis(asset_id: str):
    rows = q("""
        SELECT f.finding_id, f.rca_summary, f.recommended_action,
               e2.fault_pattern_id, e2.severity, e2.probable_mode,
               en.predicted_pattern, en.confidence, en.probabilities,
               en.top_factors, en.similar_reports, en.enriched_by
        FROM OEE_DB.ANALYTICS.FINDINGS f
        JOIN OEE_DB.ANALYTICS.ANOMALY_EVENTS e2 ON e2.event_id=f.event_id
        LEFT JOIN OEE_DB.ANALYTICS.FINDING_ENRICHMENT en
          ON en.finding_id=f.finding_id
        WHERE f.asset_id=%s ORDER BY f.finding_id DESC LIMIT 1""", (asset_id,))
    if not rows:
        raise HTTPException(404, "no diagnosis")
    import json as _j
    r = rows[0]
    return {"finding_id": r["FINDING_ID"], "rca_summary": r["RCA_SUMMARY"],
            "recommended_action": r["RECOMMENDED_ACTION"],
            "fault_pattern_id": r["FAULT_PATTERN_ID"], "severity": r["SEVERITY"],
            "probable_mode": r["PROBABLE_MODE"],
            "predicted_pattern": r["PREDICTED_PATTERN"],
            "confidence": float(r["CONFIDENCE"]) if r["CONFIDENCE"] is not None else None,
            "probabilities": _j.loads(r["PROBABILITIES"]) if r["PROBABILITIES"] else {},
            "top_factors": _j.loads(r["TOP_FACTORS"]) if r["TOP_FACTORS"] else [],
            "similar_reports": _j.loads(r["SIMILAR_REPORTS"]) if r["SIMILAR_REPORTS"] else [],
            "enriched_by": r["ENRICHED_BY"]}


@app.get("/api/live/{asset_id}")
def get_live(asset_id: str, sensor: str = "VIBRATION_RMS", seconds: int = 600):
    minutes = max(1, seconds // 60)
    rows = q("""
        SELECT ts, value FROM OEE_DB.OT.RAW_TELEMETRY
        WHERE asset_id=%s AND sensor_type=%s
          AND ts > DATEADD(minute, -%s, (SELECT MAX(ts) FROM OEE_DB.OT.RAW_TELEMETRY
                                         WHERE asset_id=%s AND sensor_type=%s))
        ORDER BY ts""", (asset_id, sensor, minutes, asset_id, sensor))
    if not rows:
        raise HTTPException(404, f"no live data {asset_id}/{sensor}")
    pts = [float(r["VALUE"]) for r in rows]
    # anomaly band: open event on this asset whose pattern maps to this sensor
    ev = q("""
        SELECT probable_mode, fault_pattern_id FROM OEE_DB.ANALYTICS.ANOMALY_EVENTS
        WHERE asset_id=%s AND status IN ('NEW','INVESTIGATING','ACTIONED')
        LIMIT 1""", (asset_id,))
    anomaly = []
    if ev:
        mode = ev[0]["PROBABLE_MODE"]
        sensor_map = {"BEARING_WEAR": ("VIBRATION_RMS", "BEARING_TEMP"),
                      "COOLING_DEGRADATION": ("BEARING_TEMP",),
                      "SENSOR_FAULT": ("VIBRATION_RMS",),
                      "BELT_SLIP_RPM": ("RPM",)}
        if sensor in sensor_map.get(mode, ()):
            anomaly.append({"start": 0, "end": len(pts),
                            "label": f"{mode.replace('_',' ')} — {ev[0]['FAULT_PATTERN_ID']}"})
    n = len(pts)
    rms = (sum(v * v for v in pts) / n) ** 0.5
    base = q("""
        SELECT MEDIAN(value) b FROM OEE_DB.OT.RAW_TELEMETRY
        WHERE asset_id=%s AND sensor_type=%s
          AND ts BETWEEN DATEADD(day,-31,(SELECT MAX(ts) FROM OEE_DB.OT.RAW_TELEMETRY))
                     AND DATEADD(day,-3,(SELECT MAX(ts) FROM OEE_DB.OT.RAW_TELEMETRY))""",
        (asset_id, sensor))
    return {"asset_id": asset_id, "sensor": sensor,
            "t0": 0, "hz": 0.2,
            "baseline": float(base[0]["B"] or 0),
            "points": pts, "anomaly": anomaly,
            "stats": {"rms": round(rms, 2), "peak": round(max(pts), 2),
                      "avg": round(sum(pts) / n, 2)}}
