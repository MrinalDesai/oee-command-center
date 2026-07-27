"""
llm_worker.py — Narrative sidecar for the Diagnose layer.

Cortex COMPLETE is the production path for RCA narratives; it is gated on
trial accounts (platform-wide change, June 2026). This worker is the
pluggable fallback: it polls ANALYTICS.FINDINGS for rows with
rca_summary = '[PENDING_NARRATIVE]', generates a grounded narrative from
the stored evidence dossier via a local Ollama model, and writes it back.

Same grounding contract as the Cortex version: evidence-only, WO citations,
no invented facts, < 200 words.

Env (same as kafka_to_snowflake.py plus optional model override):
    SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER / SNOWFLAKE_PASSWORD
    OLLAMA_MODEL   (default: qwen3.6)
    OLLAMA_URL     (default: http://localhost:11434)

Usage:  python src/llm_worker.py           # poll loop, Ctrl+C to stop
        python src/llm_worker.py --once    # single pass (useful in demos)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests
import snowflake.connector

POLL_SECONDS = 10
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.6")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

PROMPT_TEMPLATE = """You are a reliability engineer writing a root-cause finding for a maintenance planner.

Use ONLY the evidence JSON below. Cite work order IDs (e.g. WO-24290) when you reference past repairs. Do not invent facts, measurements, or history not present in the evidence. Do not describe outcomes or asset states (e.g. "no issues since") beyond what the work-order notes explicitly state.

Units: vibration values are mm/s RMS; temperatures are degrees C; slopes are per day. "Criticality" is the asset's business-importance rating, not a threshold.

Structure your answer as plain text, under 150 words total (hard limit - finish all four parts):
1. What was observed (use the actual numbers from detection_features, with correct units).
2. Probable failure mode and confidence.
3. Supporting history, citing specific work orders.
4. Urgency and consequence of inaction.

Probable mode: {mode}
Severity: {severity}

Evidence JSON:
{evidence}
"""

PENDING = "[PENDING_NARRATIVE]"


def connect() -> snowflake.connector.SnowflakeConnection:
    missing = [k for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")
               if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}")
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse="OEE_WH", database="OEE_DB", schema="ANALYTICS",
    )


def generate(evidence: dict, mode: str, severity: str) -> str:
    prompt = PROMPT_TEMPLATE.format(
        mode=mode, severity=severity,
        evidence=json.dumps(evidence, indent=1, default=str))
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": MODEL, "prompt": prompt, "stream": False,
              "options": {"temperature": 0.2, "num_predict": 600}},
        timeout=180,
    )
    resp.raise_for_status()
    text = resp.json().get("response", "").strip()
    if not text:
        raise RuntimeError("Empty response from model")
    return text[:7900]  # column headroom


def process_pending(conn) -> int:
    cur = conn.cursor(snowflake.connector.DictCursor)
    cur.execute("""
        SELECT f.finding_id, f.evidence_json,
               e.probable_mode, e.severity
        FROM ANALYTICS.FINDINGS f
        JOIN ANALYTICS.ANOMALY_EVENTS e ON e.event_id = f.event_id
        WHERE f.rca_summary = %s
        ORDER BY f.finding_id
    """, (PENDING,))
    rows = cur.fetchall()
    done = 0
    for row in rows:
        fid = row["FINDING_ID"]
        try:
            evidence = json.loads(row["EVIDENCE_JSON"]) \
                if isinstance(row["EVIDENCE_JSON"], str) else row["EVIDENCE_JSON"]
            narrative = generate(evidence, row["PROBABLE_MODE"], row["SEVERITY"])
            cur.execute(
                "UPDATE ANALYTICS.FINDINGS SET rca_summary = %s WHERE finding_id = %s",
                (f"{narrative}\n\n[generated: {MODEL} local | cortex pending access]", fid))
            conn.commit()
            done += 1
            print(f"finding {fid}: narrative written ({len(narrative)} chars)")
        except Exception as exc:  # one bad finding must not stall the queue
            print(f"finding {fid}: FAILED - {exc}")
    cur.close()
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single pass, then exit")
    args = ap.parse_args()

    # fail fast if ollama isn't serving
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).raise_for_status()
    except Exception:
        sys.exit(f"Ollama not reachable at {OLLAMA_URL} — is 'ollama serve' running?")

    conn = connect()
    print(f"llm_worker: model={MODEL} poll={POLL_SECONDS}s "
          f"{'(single pass)' if args.once else '(Ctrl+C to stop)'}")
    try:
        while True:
            n = process_pending(conn)
            if args.once:
                print(f"Done: {n} narrative(s).")
                break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
