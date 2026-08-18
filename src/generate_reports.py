"""
generate_reports.py — Historical repair-report corpus (scanned-look PDFs).

Fault-pattern catalog (unique IDs, referenced by detection events later):
    FP-01  BEARING_WEAR
    FP-02  COOLING_DEGRADATION
    FP-03  SENSOR_FAULT
    FP-04  BELT_SLIP_RPM

5 historical reports per pattern (20 PDFs). Fleet-learning premise: assets
share model numbers, so a pattern documented on one unit trains detection
for its siblings. Reports mirror the structured WO history where WOs exist
(WO-24101/24188/24290/24255/24333) and extend it with older episodes on
sibling units.

Outputs (./reports/):
    RPT-<n>.pdf          scanned-look report (jittered "hand" entries,
                         page rotation, speckle noise, signature scribble)
    reports_index.csv    ground truth for extraction validation
Usage: python src/generate_reports.py [--outdir reports] [--seed 7]
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

W, H = A4

TECHS = ["R. Naik", "S. Kadam", "P. Fernandes", "A. Shirodkar", "M. D'Souza", "V. Gawas"]

PATTERNS = {
    "FP-01": ("BEARING_WEAR", [
        ("AST-003", "ATLAS-GA30", "WO-24101", "Comp tripped high vib alarm 8.2mm/s. NDE 6312 brg cage broken, rollers pitted, inner race scored.", "Grease contamination via auto-luber", "BRG-6312-2RS x2, GRS-EP2", 9.5),
        ("AST-009", "ABB-M3BP-180", "WO-24290", "DE brg failed night shift, line down. Vib trending up 10 days, alert missed. 6316 seized, pressed out.", "End of brg life ~14 months duty, monitoring gap", "BRG-6316-C3 x2", 12.0),
        ("AST-007", "ATLAS-GA30", None, "Vib rose from 3.4 to 7+ over a week, NDE brg rough on stethoscope, temp up 8C.", "Brg wear early stage, caught on rounds", "BRG-6312-2RS x2, GRS-EP2", 6.0),
        ("AST-005", "ABB-M3BP-160", None, "Main motor vib 6.8mm/s and climbing, brg temp 74C. Axial play felt at DE.", "DE brg wear, lubrication starvation suspected", "BRG-6312-2RS x1, GRS-EP2", 7.5),
        ("AST-001", "ABB-M3BP-160", None, "Vib alarm 8mm/s, brg noisy. Cage wear visible on strip down, rollers dull.", "Normal wear, PM interval too long for duty", "BRG-6312-2RS x2", 8.0),
    ]),
    "FP-02": ("COOLING_DEGRADATION", [
        ("AST-011", "DAIKIN-JT160", "WO-24255", "Chiller disch temp creeping 2 wks, approach temp widened. Condenser coil choked with dust/fluff.", "Packing area extraction not working, housekeeping", "FLT-COND-JT160, COIL-CLEAN-KIT", 4.5),
        ("AST-003", "ATLAS-GA30", None, "Comp running 78C vs 71C normal, vib normal. Cooler fins packed with dust.", "Blocked cooler, ambient dust ingress", "COIL-CLEAN-KIT", 3.0),
        ("AST-007", "ATLAS-GA30", None, "Discharge temp high alarm 82C. Aftercooler fouled, fan belt glazed.", "Cooler fouling + fan belt slip", "COIL-CLEAN-KIT, BELT-SPB-2500", 4.0),
        ("AST-011", "DAIKIN-JT160", None, "Head pressure high, temp trending up 10 days. Cond filter overdue.", "Filter overdue - PM missed during shutdown", "FLT-COND-JT160", 2.5),
        ("AST-006", "REXROTH-A10", None, "Hyd oil temp 68C vs 60 normal, vib ok. Heat exchanger scaled inside.", "Cooling water hardness, exchanger scaling", "COIL-CLEAN-KIT", 5.0),
    ]),
    "FP-03": ("SENSOR_FAULT", [
        ("AST-010", "KSB-ETN-100", "WO-24333", "Vib reading flat 2.9 exactly for days, pump sounds normal. Accel cable chafed thru at gland.", "Cable chafe on steam line route", "TX-VIB-100mV, CBL-M12-5M", 1.0),
        ("AST-002", "KSB-ETN-080", None, "Temp reading stuck 55.0 for 3 shifts, pump normal on touch. RTD open circuit intermittent.", "RTD lead fatigue at terminal head", "CBL-M12-5M", 1.5),
        ("AST-008", "CG-ND132", None, "Vib flatline zero, fan clearly running. Accel mount stud sheared, sensor hanging.", "Mount stud failure - vibration fatigue", "TX-VIB-100mV", 1.0),
        ("AST-012", "SIEM-1LE1", None, "Current reading frozen mid-value, agitator fine. CT wiring loose in panel.", "Loose terminal, panel vibration", None, 0.5),
        ("AST-005", "ABB-M3BP-160", None, "Vib stuck at 2.0 for a week, quality flag still GOOD. Flag logic only checks range not variance.", "Sensor stuck + monitoring flag gap", "TX-VIB-100mV", 1.0),
    ]),
    "FP-04": ("BELT_SLIP_RPM", [
        ("AST-004", "SIEM-1LE1", None, "Conveyor speed hunting +-40rpm, squeal on load steps. Belt glazed and loose.", "Belt tension lost, glazing from slip", "BELT-SPB-2500", 2.0),
        ("AST-004", "SIEM-1LE1", None, "RPM dips under load, product spacing drifting. Belt worn, sheave groove polished.", "Belt end of life, sheave wear starting", "BELT-SPB-2500", 3.0),
        ("AST-012", "SIEM-1LE1", None, "Agitator speed unstable, slipping on start. Belt oil-contaminated from gearbox leak.", "Oil on belt - gearbox seal weep", "BELT-SPB-2500, SEAL-TC-50x72", 4.0),
        ("AST-008", "CG-ND132", None, "Fan rpm sagging 5% intermittent, airflow alarms. Belt stretched beyond adjuster range.", "Belt stretched, adjuster at limit", "BELT-SPB-2500", 2.5),
        ("AST-004", "SIEM-1LE1", None, "Speed oscillation with 8s period under full load. Tension ok, sheave key worn.", "Sheave key wear - backlash hunting", None, 5.0),
    ]),
}


def hand_text(c: canvas.Canvas, x: float, y: float, text: str,
              rng: random.Random, size: float = 11, color=(0.10, 0.12, 0.35)):
    """Jittered per-word 'handwriting' in blue-ink oblique."""
    c.saveState()
    c.setFillColorRGB(*color)
    cx = x
    for word in text.split(" "):
        c.saveState()
        c.translate(cx, y + rng.uniform(-1.2, 1.2))
        c.rotate(rng.uniform(-2.0, 2.0))
        c.setFont("Helvetica-Oblique", size + rng.uniform(-0.6, 0.6))
        c.drawString(0, 0, word)
        c.restoreState()
        cx += c.stringWidth(word + " ", "Helvetica-Oblique", size)
        if cx > W - 60:  # wrap
            cx = x
            y -= size + 4
    c.restoreState()
    return y


def field(c, x, y, label, w=160):
    c.setFont("Helvetica-Bold", 8)
    c.setFillColorRGB(0.25, 0.25, 0.25)
    c.drawString(x, y, label.upper())
    c.setLineWidth(0.6)
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.line(x, y - 16, x + w, y - 16)


def speckle(c, rng, n=350):
    c.saveState()
    for _ in range(n):
        g = rng.uniform(0.55, 0.85)
        c.setFillColorRGB(g, g, g)
        r = rng.uniform(0.2, 0.9)
        c.circle(rng.uniform(0, W), rng.uniform(0, H), r, stroke=0, fill=1)
    # a fold line and a coffee-ish blot occasionally
    if rng.random() < 0.5:
        c.setStrokeColorRGB(0.82, 0.82, 0.82)
        c.setLineWidth(0.8)
        yy = rng.uniform(H * 0.3, H * 0.7)
        c.line(0, yy, W, yy)
    c.restoreState()


def signature(c, x, y, rng):
    c.saveState()
    c.setStrokeColorRGB(0.10, 0.12, 0.35)
    c.setLineWidth(1.1)
    p = c.beginPath()
    p.moveTo(x, y)
    for i in range(4):
        p.curveTo(x + 10 + i * 14 + rng.uniform(-4, 4), y + rng.uniform(4, 14),
                  x + 18 + i * 14 + rng.uniform(-4, 4), y - rng.uniform(4, 12),
                  x + 26 + i * 14, y + rng.uniform(-3, 3))
    c.drawPath(p)
    c.restoreState()


def make_report(path: Path, rpt_id: str, fp_id: str, mode: str, row, ts: datetime,
                rng: random.Random):
    asset, model, wo_ref, symptoms, diagnosis, parts, downtime = row
    tech = rng.choice(TECHS)
    c = canvas.Canvas(str(path), pagesize=A4)

    # whole-page scan rotation
    c.saveState()
    c.translate(W / 2, H / 2)
    c.rotate(rng.uniform(-1.1, 1.1))
    c.translate(-W / 2, -H / 2)

    speckle(c, rng)

    # form frame + header
    c.setStrokeColorRGB(0.3, 0.3, 0.3)
    c.setLineWidth(1.2)
    c.rect(36, 36, W - 72, H - 72)
    c.setFont("Helvetica-Bold", 15)
    c.setFillColorRGB(0.15, 0.15, 0.15)
    c.drawCentredString(W / 2, H - 70, "MAINTENANCE  &  REPAIR  REPORT")
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(W / 2, H - 84, "Plant Engineering Dept.  ·  Form ME-07 Rev C")
    c.setLineWidth(0.8)
    c.line(36, H - 96, W - 36, H - 96)

    y0 = H - 126
    field(c, 60, y0, "Report No."); hand_text(c, 66, y0 - 13, rpt_id, rng, 12)
    field(c, 240, y0, "Fault Pattern ID", 120); hand_text(c, 246, y0 - 13, fp_id, rng, 12)
    field(c, 400, y0, "Date of Failure", 130)
    hand_text(c, 406, y0 - 13, ts.strftime("%d/%m/%Y  %H:%M"), rng, 11)

    y1 = y0 - 46
    field(c, 60, y1, "Asset ID"); hand_text(c, 66, y1 - 13, asset, rng, 12)
    field(c, 240, y1, "Model No.", 120); hand_text(c, 246, y1 - 13, model, rng, 11)
    field(c, 400, y1, "Linked WO", 130)
    hand_text(c, 406, y1 - 13, wo_ref or "-", rng, 11)

    y2 = y1 - 52
    field(c, 60, y2, "Symptoms Observed", W - 132)
    hand_text(c, 66, y2 - 15, symptoms, rng, 11)

    y3 = y2 - 78
    field(c, 60, y3, "Diagnosis / Root Cause", W - 132)
    hand_text(c, 66, y3 - 15, diagnosis, rng, 11)

    y4 = y3 - 60
    field(c, 60, y4, "Parts Replaced", W - 132)
    hand_text(c, 66, y4 - 15, parts or "nil", rng, 11)

    y5 = y4 - 52
    field(c, 60, y5, "Downtime (hrs)", 100)
    hand_text(c, 66, y5 - 13, str(downtime), rng, 12)
    field(c, 240, y5, "Fault Category", 180)
    hand_text(c, 246, y5 - 13, mode.replace("_", " ").title(), rng, 11)

    y6 = y5 - 60
    field(c, 60, y6, "Technician", 160)
    hand_text(c, 66, y6 - 13, tech, rng, 11)
    field(c, 300, y6, "Signature", 180)
    signature(c, 310, y6 - 16, rng)

    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(40, 42, f"Scanned copy · {rpt_id} · retain 5 years")
    c.restoreState()
    c.save()
    return tech


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    out = Path(args.outdir)
    out.mkdir(exist_ok=True)

    # dates: mirrored WOs keep plausible recent dates; the rest spread over 3 years
    now = datetime.now()
    index = []
    n = 4001
    for fp_id, (mode, rows) in PATTERNS.items():
        for row in rows:
            rpt_id = f"RPT-{n}"; n += 1
            if row[2]:  # mirrors a structured WO -> within the 90-day window
                ts = now - timedelta(days=rng.randint(20, 80),
                                     hours=rng.randint(0, 23))
            else:
                ts = now - timedelta(days=rng.randint(100, 1100),
                                     hours=rng.randint(0, 23))
            tech = make_report(out / f"{rpt_id}.pdf", rpt_id, fp_id, mode, row, ts, rng)
            index.append(dict(report_id=rpt_id, fault_pattern_id=fp_id,
                              fault_mode=mode, asset_id=row[0], model_no=row[1],
                              linked_wo=row[2] or "", failure_ts=ts.isoformat(),
                              symptoms=row[3], diagnosis=row[4],
                              parts_replaced=row[5] or "", downtime_hours=row[6],
                              technician=tech))

    with open(out / "reports_index.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(index[0].keys()))
        w.writeheader(); w.writerows(index)

    print(f"{len(index)} reports -> {out.resolve()}")
    for fp_id, (mode, rows) in PATTERNS.items():
        print(f"  {fp_id} {mode}: {len(rows)}")


if __name__ == "__main__":
    main()
