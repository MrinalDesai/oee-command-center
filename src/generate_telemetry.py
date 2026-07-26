"""
generate_telemetry.py — Synthetic OT + ERP data for OEE Command Center.

Generates 90 days of history for 12 assets across 3 lines:
  - OT: sensor telemetry (VIBRATION_RMS, BEARING_TEMP, RPM, CURRENT_DRAW)
    at 5-minute cadence, with realistic baselines + injected failure signatures.
  - ERP: asset master, work-order history (with technician free-text notes,
    cross-referenced to the injected failures), spare parts, production schedule.

Failure signatures injected:
  1. BEARING_WEAR        — exponential vibration ramp over ~10 days,
                            bearing temp follows with lag. (x3 historical, x1 ACTIVE)
  2. COOLING_DEGRADATION — slow linear temp rise, vibration flat. (x1 historical)
  3. SENSOR_FAULT        — stuck-at value, quality flag stays GOOD. (x1 historical)

The ACTIVE bearing-wear event ramps through "now" without a completed WO —
that is the live demo hook the detection pipeline must catch.

Output: CSV files in ./data/ ready for PUT + COPY INTO (or direct load via CoCo).

Usage:
    python src/generate_telemetry.py [--days 90] [--seed 42] [--outdir data]
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

CADENCE_MIN = 5  # minutes between readings

# ── Asset fleet ──────────────────────────────────────────────────────────────

@dataclass
class Asset:
    asset_id: str
    asset_name: str
    asset_type: str      # MOTOR | PUMP | COMPRESSOR
    line_id: str
    model_no: str
    install_date: str
    criticality: str     # HIGH | MEDIUM | LOW
    # baseline operating points
    vib_base: float      # mm/s RMS
    temp_base: float     # deg C
    rpm_base: float
    amp_base: float


FLEET: list[Asset] = [
    Asset("AST-001", "Line1 Main Drive Motor",   "MOTOR",      "L1", "ABB-M3BP-160", "2019-03-12", "HIGH",   2.1, 62.0, 1480, 42.0),
    Asset("AST-002", "Line1 Coolant Pump",       "PUMP",       "L1", "KSB-ETN-080",  "2020-07-01", "MEDIUM", 2.8, 55.0, 2900, 18.5),
    Asset("AST-003", "Line1 Air Compressor",     "COMPRESSOR", "L1", "ATLAS-GA30",   "2018-11-20", "HIGH",   3.2, 71.0, 2950, 55.0),
    Asset("AST-004", "Line1 Conveyor Motor",     "MOTOR",      "L1", "SIEM-1LE1",    "2021-02-14", "LOW",    1.9, 58.0,  960, 12.0),
    Asset("AST-005", "Line2 Main Drive Motor",   "MOTOR",      "L2", "ABB-M3BP-160", "2019-05-30", "HIGH",   2.0, 61.0, 1480, 41.5),
    Asset("AST-006", "Line2 Hydraulic Pump",     "PUMP",       "L2", "REXROTH-A10",  "2020-01-22", "MEDIUM", 3.0, 64.0, 1800, 27.0),
    Asset("AST-007", "Line2 Air Compressor",     "COMPRESSOR", "L2", "ATLAS-GA30",   "2017-09-08", "HIGH",   3.4, 72.5, 2950, 56.0),
    Asset("AST-008", "Line2 Exhaust Fan Motor",  "MOTOR",      "L2", "CG-ND132",     "2022-06-10", "LOW",    2.2, 54.0, 1440, 9.5),
    Asset("AST-009", "Line3 Main Drive Motor",   "MOTOR",      "L3", "ABB-M3BP-180", "2018-04-02", "HIGH",   2.3, 63.5, 1475, 48.0),
    Asset("AST-010", "Line3 Process Pump",       "PUMP",       "L3", "KSB-ETN-100",  "2019-12-15", "MEDIUM", 2.9, 57.0, 2900, 21.0),
    Asset("AST-011", "Line3 Chiller Compressor", "COMPRESSOR", "L3", "DAIKIN-JT160", "2020-10-05", "HIGH",   3.1, 68.0, 2900, 52.0),
    Asset("AST-012", "Line3 Agitator Motor",     "MOTOR",      "L3", "SIEM-1LE1",    "2021-08-19", "LOW",    2.4, 59.0,  720, 14.0),
]

SENSORS = ("VIBRATION_RMS", "BEARING_TEMP", "RPM", "CURRENT_DRAW")

# ── Failure event plan ───────────────────────────────────────────────────────
# day offsets are relative to history start (day 0) .. history end (day N).
# "end_day = None" means the ramp runs through the end of history (ACTIVE).

@dataclass
class FailureEvent:
    asset_id: str
    mode: str            # BEARING_WEAR | COOLING_DEGRADATION | SENSOR_FAULT
    start_day: int
    end_day: int | None  # day the asset failed / was repaired; None = still active
    wo: dict | None      # completed work order (None for the active event)


def build_failure_plan(days: int) -> list[FailureEvent]:
    return [
        FailureEvent(
            "AST-003", "BEARING_WEAR", start_day=8, end_day=18,
            wo=dict(
                wo_id="WO-24101", wo_type="CORRECTIVE",
                failure_mode="BEARING_WEAR",
                parts_used="BRG-6312-2RS x2, GRS-EP2 grease",
                downtime_hours=9.5,
                technician_notes=(
                    "Comp tripped on high vib alarm 8.2mm/s. Opened NDE housing, "
                    "6312 brg cage broken, rollers pitted. Inner race scored. "
                    "Replaced both DE+NDE brgs BRG-6312-2RS, regreased EP2. "
                    "Shaft OK, no scoring. Aligned to 0.03mm. Test run 2hr vib 3.1 "
                    "steady. Suspect grease contamination - told opr to check "
                    "auto-luber weekly. PM interval should be reduced imo."
                ),
            ),
        ),
        FailureEvent(
            "AST-006", "BEARING_WEAR", start_day=25, end_day=34,
            wo=dict(
                wo_id="WO-24188", wo_type="CORRECTIVE",
                failure_mode="BEARING_WEAR",
                parts_used="BRG-NU210 x1, SEAL-TC-50x72",
                downtime_hours=6.0,
                technician_notes=(
                    "Hyd pump noisy since Tue, vib climbing on trend. Pulled pump, "
                    "NU210 roller brg worn, radial play excessive. Seal was leaking, "
                    "oil level low - probable cause. Fitted new brg + shaft seal. "
                    "Topped up ISO VG46. Vib back to 2.9. Raised sep ticket for "
                    "oil level sensor - not reading right."
                ),
            ),
        ),
        FailureEvent(
            "AST-009", "BEARING_WEAR", start_day=48, end_day=58,
            wo=dict(
                wo_id="WO-24290", wo_type="CORRECTIVE",
                failure_mode="BEARING_WEAR",
                parts_used="BRG-6316-C3 x2",
                downtime_hours=12.0,
                technician_notes=(
                    "L3 main motor DE brg failed on night shift, line down. Vib was "
                    "trending up 10 days but alert missed (dashboard only, nobody "
                    "checked). 6316 brg seized, had to press out. Minor journal "
                    "damage, polished ok. New brgs C3 clearance both ends. "
                    "Balanced coupling. 14 months since last brg change on this "
                    "asset - matches MTBF for this duty. Recommend predictive "
                    "monitoring, this was avoidable."
                ),
            ),
        ),
        FailureEvent(
            "AST-011", "COOLING_DEGRADATION", start_day=35, end_day=52,
            wo=dict(
                wo_id="WO-24255", wo_type="CORRECTIVE",
                failure_mode="COOLING_DEGRADATION",
                parts_used="FLT-COND-JT160, COIL-CLEAN-KIT",
                downtime_hours=4.5,
                technician_notes=(
                    "Chiller disch temp creeping up 2wks, approach temp widened. "
                    "Condenser coil choked with dust/fluff from packing area. "
                    "Chemical cleaned coils, replaced cond filter. Temp back to "
                    "68C nominal. Housekeeping issue - packing area extraction "
                    "not working properly, flagged to facilities."
                ),
            ),
        ),
        FailureEvent(
            "AST-010", "SENSOR_FAULT", start_day=60, end_day=66,
            wo=dict(
                wo_id="WO-24333", wo_type="CORRECTIVE",
                failure_mode="SENSOR_FAULT",
                parts_used="TX-VIB-100mV x1, CBL-M12-5M",
                downtime_hours=1.0,
                technician_notes=(
                    "Vib reading flat 2.9 exactly for days - obviously stuck, pump "
                    "sounded normal. Accelerometer cable chafed thru at gland, "
                    "intermittent then failed steady. Replaced sensor + cable, "
                    "rerouted away from steam line. Reading live again. NOTE: "
                    "system showed GOOD quality flag whole time - flag logic only "
                    "checks range not variance. Should flag stuck values."
                ),
            ),
        ),
        # THE ACTIVE EVENT — bearing wear developing on AST-007, ramps through "now".
        FailureEvent("AST-007", "BEARING_WEAR", start_day=days - 8, end_day=None, wo=None),
    ]


# ── Preventive/misc work orders to pad history realistically ────────────────

PM_NOTE_TEMPLATES = [
    "Routine PM done. Greased brgs, checked alignment, all params nominal.",
    "Quarterly PM. Changed oil, cleaned strainer. Vib/temp within limits.",
    "PM as per schedule. Belt tension adjusted. No abnormality observed.",
    "Annual PM. Meggered motor 550Mohm OK. Cleaned cooling fins. Ok to run.",
    "PM done with line stop. Coupling insert inspected, 30% wear, will change next PM.",
]


# ── Signal generation ────────────────────────────────────────────────────────

def diurnal_shift_pattern(ts_index: pd.DatetimeIndex) -> np.ndarray:
    """Load factor: 3-shift pattern with lower load on night shift + weekend dip."""
    hours = ts_index.hour.values
    dow = ts_index.dayofweek.values
    load = np.where((hours >= 6) & (hours < 14), 1.00,          # morning shift
                    np.where((hours >= 14) & (hours < 22), 0.97,  # afternoon
                             0.88))                               # night
    load = load * np.where(dow >= 5, 0.75, 1.0)                  # weekend
    return load


def generate_asset_telemetry(
    asset: Asset,
    ts_index: pd.DatetimeIndex,
    events: list[FailureEvent],
    rng: np.random.Generator,
    start: datetime,
) -> pd.DataFrame:
    n = len(ts_index)
    load = diurnal_shift_pattern(ts_index)
    day_of = (ts_index - start).total_seconds() / 86400.0  # float days since start

    # baselines modulated by load + noise
    vib = asset.vib_base * (0.85 + 0.15 * load) + rng.normal(0, 0.08 * asset.vib_base, n)
    temp = asset.temp_base * (0.92 + 0.08 * load) + rng.normal(0, 0.9, n)
    rpm = asset.rpm_base * load + rng.normal(0, 0.004 * asset.rpm_base, n)
    amp = asset.amp_base * load + rng.normal(0, 0.03 * asset.amp_base, n)
    quality = np.full(n, "GOOD", dtype=object)

    for ev in (e for e in events if e.asset_id == asset.asset_id):
        end_day = ev.end_day if ev.end_day is not None else day_of[-1] + 0.001
        mask = (day_of >= ev.start_day) & (day_of <= end_day)
        prog = np.clip((day_of - ev.start_day) / max(end_day - ev.start_day, 0.5), 0, 1)

        if ev.mode == "BEARING_WEAR":
            # vibration: exponential ramp to ~3.5x baseline at failure point
            ramp = np.expm1(2.2 * prog) / np.expm1(2.2)  # 0..1, convex
            vib_add = 2.5 * asset.vib_base * ramp
            # temp follows vibration with ~1 day lag, up to +12C
            prog_lag = np.clip(prog - (1.0 / max(end_day - ev.start_day, 1)), 0, 1)
            temp_add = 12.0 * (np.expm1(2.2 * prog_lag) / np.expm1(2.2))
            # amps creep slightly with friction
            amp_add = 0.06 * asset.amp_base * prog
            vib = np.where(mask, vib + vib_add, vib)
            temp = np.where(mask, temp + temp_add, temp)
            amp = np.where(mask, amp + amp_add, amp)
            # extra high-freq jitter as damage progresses
            vib = np.where(mask, vib + rng.normal(0, 0.15, n) * prog, vib)

        elif ev.mode == "COOLING_DEGRADATION":
            # slow linear temp rise up to +9C; vibration unaffected
            temp = np.where(mask, temp + 9.0 * prog, temp)
            amp = np.where(mask, amp + 0.04 * asset.amp_base * prog, amp)

        elif ev.mode == "SENSOR_FAULT":
            # vibration channel sticks at a frozen value; quality flag stays GOOD
            frozen = round(asset.vib_base * 1.02, 1)
            vib = np.where(mask, frozen, vib)
            # (the deliberate trap: flag logic "only checks range not variance")

        # post-repair: brief clean period is already handled by mask ending.

    frames = []
    for sensor, series in (
        ("VIBRATION_RMS", vib),
        ("BEARING_TEMP", temp),
        ("RPM", rpm),
        ("CURRENT_DRAW", amp),
    ):
        frames.append(pd.DataFrame({
            "asset_id": asset.asset_id,
            "sensor_type": sensor,
            "ts": ts_index,
            "value": np.round(series, 3),
            "quality_flag": quality,
        }))
    return pd.concat(frames, ignore_index=True)


# ── ERP generators ───────────────────────────────────────────────────────────

def generate_work_orders(events: list[FailureEvent], start: datetime, days: int,
                         rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    # corrective WOs from the failure plan
    for ev in events:
        if ev.wo is None:
            continue
        opened = start + timedelta(days=ev.end_day, hours=int(rng.integers(6, 20)))
        rows.append({
            "wo_id": ev.wo["wo_id"], "asset_id": ev.asset_id,
            "wo_type": ev.wo["wo_type"],
            "opened_ts": opened,
            "closed_ts": opened + timedelta(hours=ev.wo["downtime_hours"]),
            "failure_mode": ev.wo["failure_mode"],
            "technician_notes": ev.wo["technician_notes"],
            "parts_used": ev.wo["parts_used"],
            "downtime_hours": ev.wo["downtime_hours"],
        })
    # preventive WOs: each asset roughly monthly
    wo_seq = 24400
    for asset in FLEET:
        day = int(rng.integers(3, 18))
        while day < days:
            opened = datetime(*(start + timedelta(days=day)).timetuple()[:3], 9, 0)
            dur = round(float(rng.uniform(1.0, 3.5)), 1)
            rows.append({
                "wo_id": f"WO-{wo_seq}", "asset_id": asset.asset_id,
                "wo_type": "PREVENTIVE",
                "opened_ts": opened,
                "closed_ts": opened + timedelta(hours=dur),
                "failure_mode": None,
                "technician_notes": random.choice(PM_NOTE_TEMPLATES),
                "parts_used": "GRS-EP2 grease" if rng.random() < 0.5 else None,
                "downtime_hours": dur,
            })
            wo_seq += 1
            day += int(rng.integers(26, 34))
    return pd.DataFrame(rows)


def generate_spare_parts() -> pd.DataFrame:
    parts = [
        ("BRG-6312-2RS", "Deep groove ball bearing 6312 2RS", 4, 7, 3200.0),
        ("BRG-6316-C3",  "Deep groove ball bearing 6316 C3",  2, 14, 5400.0),
        ("BRG-NU210",    "Cylindrical roller bearing NU210",  3, 10, 4100.0),
        ("SEAL-TC-50x72", "Shaft seal TC 50x72x8",            8, 5, 240.0),
        ("GRS-EP2",      "Lithium EP2 grease 1kg",           12, 3, 650.0),
        ("FLT-COND-JT160", "Condenser filter JT160",          2, 21, 1850.0),
        ("COIL-CLEAN-KIT", "Coil chemical cleaning kit",      5, 7, 900.0),
        ("TX-VIB-100mV", "Accelerometer 100mV/g M12",         1, 30, 7800.0),
        ("CBL-M12-5M",   "Sensor cable M12 5m shielded",      6, 10, 450.0),
        ("BELT-SPB-2500", "V-belt SPB 2500",                 10, 5, 380.0),
    ]
    return pd.DataFrame(parts, columns=[
        "part_no", "part_name", "qty_on_hand", "lead_time_days", "unit_cost"])


def generate_production_schedule(events: list[FailureEvent], start: datetime,
                                 days: int, rng: np.random.Generator) -> pd.DataFrame:
    # downtime windows per line, from corrective WOs
    downtime: dict[str, list[tuple[float, float]]] = {"L1": [], "L2": [], "L3": []}
    asset_line = {a.asset_id: a.line_id for a in FLEET}
    for ev in events:
        if ev.wo is None:
            continue
        d0 = ev.end_day
        d1 = ev.end_day + ev.wo["downtime_hours"] / 24.0
        downtime[asset_line[ev.asset_id]].append((d0, d1))

    rows = []
    for line in ("L1", "L2", "L3"):
        rate = {"L1": 120, "L2": 100, "L3": 140}[line]  # units/hour planned
        for day in range(days):
            for shift in (1, 2, 3):
                shift_start_day = day + (shift - 1) * 8 / 24.0
                shift_end_day = shift_start_day + 8 / 24.0
                planned_min = 480 if (start + timedelta(days=day)).weekday() < 5 else 360
                planned = int(rate * planned_min / 60)
                # availability hit if downtime overlaps this shift
                lost = 0.0
                for (d0, d1) in downtime[line]:
                    ov = max(0.0, min(shift_end_day, d1) - max(shift_start_day, d0))
                    lost += ov * 24 * 60
                run_min = max(planned_min - lost, 0)
                perf = rng.uniform(0.90, 0.99)          # performance losses
                actual = int(rate * run_min / 60 * perf)
                good = int(actual * rng.uniform(0.965, 0.998))  # quality losses
                rows.append({
                    "line_id": line,
                    "shift_date": (start + timedelta(days=day)).date(),
                    "shift_no": shift,
                    "planned_minutes": planned_min,
                    "planned_units": planned,
                    "actual_units": actual,
                    "good_units": good,
                })
    return pd.DataFrame(rows)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--outdir", type=str, default="data")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    random.seed(args.seed)
    out = Path(args.outdir)
    out.mkdir(exist_ok=True)

    end = datetime.now().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    ts_index = pd.date_range(start, end, freq=f"{CADENCE_MIN}min", inclusive="left")

    events = build_failure_plan(args.days)

    # OT
    telemetry = pd.concat(
        (generate_asset_telemetry(a, ts_index, events, rng, start) for a in FLEET),
        ignore_index=True,
    )
    telemetry.to_csv(out / "raw_telemetry.csv", index=False)

    # ERP
    pd.DataFrame([vars(a) for a in FLEET])[[
        "asset_id", "asset_name", "asset_type", "line_id",
        "model_no", "install_date", "criticality",
    ]].to_csv(out / "asset_master.csv", index=False)
    generate_work_orders(events, start, args.days, rng).to_csv(
        out / "work_order_history.csv", index=False)
    generate_spare_parts().to_csv(out / "spare_parts_inventory.csv", index=False)
    generate_production_schedule(events, start, args.days, rng).to_csv(
        out / "production_schedule.csv", index=False)

    n_active = sum(1 for e in events if e.end_day is None)
    print(f"Telemetry rows : {len(telemetry):,}")
    print(f"Assets         : {len(FLEET)} | window: {start:%Y-%m-%d} -> {end:%Y-%m-%d}")
    print(f"Failure events : {len(events)} ({n_active} ACTIVE - demo hook on AST-007)")
    print(f"Output         : {out.resolve()}")


if __name__ == "__main__":
    main()
