"""
extract_reports.py — Document extraction over the repair-report corpus.

Production path: Snowflake Document AI / AI_PARSE_DOCUMENT (gated on trial
accounts as of Aug 2026). This is the pluggable local adapter: renders each
PDF page to an image (PyMuPDF), extracts structured fields with a local
vision model via Ollama (qwen2.5vl / llama3.2-vision), validates against
reports_index.csv ground truth, and optionally pushes to
OEE_DB.ANALYTICS.EXTRACTED_REPORTS.

Usage:
    python src/extract_reports.py                       # extract + validate
    python src/extract_reports.py --push                # also load to Snowflake
    python src/extract_reports.py --model llama3.2-vision
Env for --push: SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER / SNOWFLAKE_PASSWORD
Deps: pip install pymupdf requests pandas snowflake-connector-python
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
from pathlib import Path

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

FIELDS = ["report_id", "fault_pattern_id", "asset_id", "model_no",
          "failure_date", "linked_wo", "symptoms", "diagnosis",
          "parts_replaced", "downtime_hours", "technician"]

PROMPT = """This is a scanned maintenance & repair report form. Extract these fields and reply with ONLY a JSON object, no other text:

{
 "report_id": "(Report No., e.g. RPT-4001)",
 "fault_pattern_id": "(Fault Pattern ID, e.g. FP-01)",
 "asset_id": "(Asset ID, e.g. AST-007)",
 "model_no": "(Model No.)",
 "failure_date": "(Date of Failure as written)",
 "linked_wo": "(Linked WO, or empty string if '-')",
 "symptoms": "(Symptoms Observed, verbatim)",
 "diagnosis": "(Diagnosis / Root Cause, verbatim)",
 "parts_replaced": "(Parts Replaced, or empty string if 'nil')",
 "downtime_hours": "(Downtime hrs as a number)",
 "technician": "(Technician name)"
}

If a field is unreadable use empty string. JSON only."""


def render_page(pdf_path: Path, dpi: int = 150) -> bytes:
    import fitz  # PyMuPDF
    doc = fitz.open(pdf_path)
    pix = doc[0].get_pixmap(dpi=dpi)
    return pix.tobytes("png")


def extract_one(pdf_path: Path, model: str) -> dict:
    png = render_page(pdf_path)
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
        "model": model, "prompt": PROMPT, "stream": False,
        "images": [base64.b64encode(png).decode()],
        "options": {"temperature": 0.0, "num_predict": 700},
    }, timeout=300)
    resp.raise_for_status()
    text = resp.json().get("response", "")
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON in response: {text[:200]}")
    data = json.loads(m.group(0))
    return {f: str(data.get(f, "")).strip() for f in FIELDS}


def validate(rows: list[dict], index_csv: Path) -> None:
    truth = {r["report_id"]: r for r in csv.DictReader(open(index_csv))}
    keys = ["fault_pattern_id", "asset_id", "model_no", "linked_wo", "technician"]
    total = correct = 0
    misses = []
    for r in rows:
        t = truth.get(r["report_id"])
        if not t:
            misses.append((r["report_id"], "report_id", r["report_id"], "?"))
            continue
        for k in keys:
            total += 1
            got, want = r[k].upper().replace(" ", ""), t[k].upper().replace(" ", "")
            if got == want or (not want and got in ("", "-", "NIL")):
                correct += 1
            else:
                misses.append((r["report_id"], k, r[k], t[k]))
    pct = 100 * correct / max(total, 1)
    print(f"\nvalidation: {correct}/{total} key fields correct ({pct:.1f}%)")
    for m_ in misses[:15]:
        print("  miss:", m_)
    if len(misses) > 15:
        print(f"  ... and {len(misses) - 15} more")


def push(rows: list[dict]) -> None:
    import snowflake.connector
    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse="OEE_WH", database="OEE_DB", schema="ANALYTICS")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS OEE_DB.ANALYTICS.EXTRACTED_REPORTS (
          report_id VARCHAR(12) PRIMARY KEY, fault_pattern_id VARCHAR(6),
          asset_id VARCHAR(10), model_no VARCHAR(30), failure_date VARCHAR(30),
          linked_wo VARCHAR(12), symptoms VARCHAR(2000), diagnosis VARCHAR(2000),
          parts_replaced VARCHAR(500), downtime_hours VARCHAR(10),
          technician VARCHAR(50),
          extracted_by VARCHAR(60),
          extracted_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""")
    model_tag = f"{os.environ.get('EXTRACT_MODEL','vision-local')} local | document-ai pending access"
    for r in rows:
        cur.execute(
            "MERGE INTO OEE_DB.ANALYTICS.EXTRACTED_REPORTS t USING "
            "(SELECT %s AS report_id) s ON t.report_id = s.report_id "
            "WHEN MATCHED THEN UPDATE SET fault_pattern_id=%s, asset_id=%s, "
            "model_no=%s, failure_date=%s, linked_wo=%s, symptoms=%s, "
            "diagnosis=%s, parts_replaced=%s, downtime_hours=%s, technician=%s, "
            "extracted_by=%s "
            "WHEN NOT MATCHED THEN INSERT (report_id, fault_pattern_id, asset_id, "
            "model_no, failure_date, linked_wo, symptoms, diagnosis, "
            "parts_replaced, downtime_hours, technician, extracted_by) VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (r["report_id"], r["fault_pattern_id"], r["asset_id"], r["model_no"],
             r["failure_date"], r["linked_wo"], r["symptoms"], r["diagnosis"],
             r["parts_replaced"], r["downtime_hours"], r["technician"], model_tag,
             r["report_id"], r["fault_pattern_id"], r["asset_id"], r["model_no"],
             r["failure_date"], r["linked_wo"], r["symptoms"], r["diagnosis"],
             r["parts_replaced"], r["downtime_hours"], r["technician"], model_tag))
    conn.commit()
    print(f"pushed {len(rows)} rows -> OEE_DB.ANALYTICS.EXTRACTED_REPORTS")
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", default="reports")
    ap.add_argument("--model", default=os.environ.get("EXTRACT_MODEL", "qwen2.5vl"))
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="first N only (smoke test)")
    args = ap.parse_args()
    os.environ["EXTRACT_MODEL"] = args.model

    pdfs = sorted(Path(args.pdf_dir).glob("RPT-*.pdf"))
    if args.limit:
        pdfs = pdfs[:args.limit]
    if not pdfs:
        sys.exit(f"no RPT-*.pdf in {args.pdf_dir}")

    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).raise_for_status()
    except Exception:
        sys.exit(f"Ollama not reachable at {OLLAMA_URL}")

    rows, failed = [], []
    for p in pdfs:
        try:
            r = extract_one(p, args.model)
            rows.append(r)
            print(f"{p.name}: {r['report_id']} {r['fault_pattern_id']} "
                  f"{r['asset_id']} ok")
        except Exception as e:
            failed.append(p.name)
            print(f"{p.name}: FAILED - {e}")

    out = Path(args.pdf_dir) / "extracted.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader(); w.writerows(rows)
    print(f"\n{len(rows)} extracted, {len(failed)} failed -> {out}")

    idx = Path(args.pdf_dir) / "reports_index.csv"
    if idx.exists():
        validate(rows, idx)
    if args.push and rows:
        push(rows)


if __name__ == "__main__":
    main()
