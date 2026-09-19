"""
embed_reports.py — Semantic retrieval layer over the repair-report corpus.

PRODUCTION PATH (preferred):
    SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', ...)
    -> VECTOR(FLOAT, 768) -> native VECTOR_COSINE_SIMILARITY.
    Runs entirely in-account via SQL; see sql/07_embed_reports.sql.

LOCAL FALLBACK (this script):
    bge-m3 embeddings via Ollama -> VECTOR(FLOAT, 1024) column -> native
    VECTOR_COSINE_SIMILARITY retrieval in plain SQL. The retrieval itself
    runs INSIDE Snowflake; only the embedding call is local. Use this path
    when Cortex is unavailable (gated trial, network restrictions, etc.).

Usage:
    python src/embed_reports.py                      # embed all + load
    python src/embed_reports.py --query "vibration rising bearing hot"
                                                     # retrieval test
Env: SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER / SNOWFLAKE_PASSWORD  (scripts/env.ps1)
Deps: requests, snowflake-connector-python. Ollama model: bge-m3.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import requests
import snowflake.connector

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = "bge-m3"
DIM = 1024


def connect():
    missing = [k for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")
               if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}")
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse="OEE_WH", database="OEE_DB", schema="ANALYTICS")


def embed(text: str) -> list[float]:
    r = requests.post(f"{OLLAMA_URL}/api/embed",
                      json={"model": MODEL, "input": text}, timeout=120)
    r.raise_for_status()
    vec = r.json()["embeddings"][0]
    if len(vec) != DIM:
        raise ValueError(f"expected {DIM} dims, got {len(vec)}")
    return vec


def load(conn) -> None:
    cur = conn.cursor(snowflake.connector.DictCursor)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS OEE_DB.ANALYTICS.REPORT_EMBEDDINGS (
          report_id VARCHAR(12) PRIMARY KEY,
          fault_pattern_id VARCHAR(6),
          asset_id VARCHAR(10),
          model_no VARCHAR(30),
          content VARCHAR(4000),
          embedding VECTOR(FLOAT, 1024),
          embedded_by VARCHAR(60) DEFAULT 'bge-m3 local | cortex-search pending access'
        )""")
    cur.execute("""SELECT report_id, fault_pattern_id, asset_id, model_no,
                          symptoms, diagnosis, parts_replaced
                   FROM OEE_DB.ANALYTICS.EXTRACTED_REPORTS""")
    rows = cur.fetchall()
    if not rows:
        sys.exit("EXTRACTED_REPORTS is empty - run extract_reports.py --push first")
    n = 0
    for r in rows:
        content = (f"Asset {r['ASSET_ID']} model {r['MODEL_NO']} "
                   f"pattern {r['FAULT_PATTERN_ID']}. "
                   f"Symptoms: {r['SYMPTOMS']} Diagnosis: {r['DIAGNOSIS']} "
                   f"Parts: {r['PARTS_REPLACED'] or 'none'}")
        vec = embed(content)
        cur.execute(
            "MERGE INTO OEE_DB.ANALYTICS.REPORT_EMBEDDINGS t "
            "USING (SELECT %s AS report_id) s ON t.report_id = s.report_id "
            "WHEN MATCHED THEN UPDATE SET content=%s, "
            "  embedding=CAST(PARSE_JSON(%s) AS VECTOR(FLOAT,1024)) "
            "WHEN NOT MATCHED THEN INSERT "
            "  (report_id, fault_pattern_id, asset_id, model_no, content, embedding) "
            "VALUES (%s,%s,%s,%s,%s, CAST(PARSE_JSON(%s) AS VECTOR(FLOAT,1024)))",
            (r["REPORT_ID"], content, json.dumps(vec),
             r["REPORT_ID"], r["FAULT_PATTERN_ID"], r["ASSET_ID"],
             r["MODEL_NO"], content, json.dumps(vec)))
        n += 1
        print(f"{r['REPORT_ID']}: embedded ({len(content)} chars)")
    conn.commit()
    print(f"\n{n} embeddings -> OEE_DB.ANALYTICS.REPORT_EMBEDDINGS")


def query(conn, text: str, k: int = 5) -> None:
    vec = embed(text)
    cur = conn.cursor()
    cur.execute(
        "SELECT report_id, fault_pattern_id, asset_id, "
        "  ROUND(VECTOR_COSINE_SIMILARITY(embedding, "
        "        CAST(PARSE_JSON(%s) AS VECTOR(FLOAT,1024))), 4) AS score, "
        "  LEFT(content, 110) "
        "FROM OEE_DB.ANALYTICS.REPORT_EMBEDDINGS "
        "ORDER BY score DESC LIMIT %s", (json.dumps(vec), k))
    print(f"\ntop {k} for: {text!r}")
    for row in cur.fetchall():
        print(f"  {row[0]}  {row[1]}  {row[2]}  score={row[3]}  | {row[4]}...")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", help="retrieval test instead of loading")
    args = ap.parse_args()

    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).raise_for_status()
    except Exception:
        sys.exit(f"Ollama not reachable at {OLLAMA_URL}")

    conn = connect()
    try:
        if args.query:
            query(conn, args.query)
        else:
            load(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
