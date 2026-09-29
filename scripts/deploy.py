"""
ForgePulse manual deploy runner.

Replaces the CoCo CLI A3 migration prompt, which is unavailable on
AI Data Cloud accounts (Cortex Code CLI subscription not enabled).

Usage:
    python scripts\\deploy.py sql\\01_schema.sql
    python scripts\\deploy.py --stage data
    python scripts\\deploy.py --verify
    python scripts\\deploy.py sql\\02_streams.sql sql\\03_procedures.sql

Reads credentials from env.ps1 environment variables.
"""

import glob
import os
import sys

import snowflake.connector as sc

EXPECTED_COUNTS = {
    "OEE_DB.OT.RAW_TELEMETRY": 1_244_160,
    "OEE_DB.OT.ASSET_MASTER": 12,
    "OEE_DB.ERP.SPARE_PARTS_INVENTORY": 41,
}

STAGE = "OEE_DB.OT.LOAD_STAGE"


def connect():
    required = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}. Run: . .\\scripts\\env.ps1")

    con = sc.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role="ACCOUNTADMIN", database="OEE_DB", schema="ANALYTICS", warehouse="OEE_WH",
    )
    cur = con.cursor()
    acct, user = cur.execute(
        "SELECT CURRENT_ORGANIZATION_NAME()||'-'||CURRENT_ACCOUNT_NAME(), CURRENT_USER()"
    ).fetchone()
    print(f"connected: {acct} / {user}")
    if acct != "YRCKWDT-CNB10903":
        resp = input(f"  !! expected YRCKWDT-CNB10903, got {acct}. continue? [y/N] ")
        if resp.strip().lower() != "y":
            sys.exit("aborted")
    return con, cur


def run_file(con, cur, path):
    print(f"\n=== {path} ===")
    with open(path, encoding="utf-8") as fh:
        sql = fh.read()
    for stmt in con.execute_string(sql, remove_comments=False):
        head = " ".join(stmt.query.strip().split())[:90]
        try:
            row = stmt.fetchone()
        except Exception:
            row = None
        print(f"  {head}\n    -> {row}")


def stage_files(cur, data_dir):
    print(f"\n=== staging {data_dir} ===")
    cur.execute(f"CREATE STAGE IF NOT EXISTS {STAGE}")
    patterns = ("*.csv", "*.csv.gz", "*.parquet", "*.json")
    files = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(data_dir, pat)))
    if not files:
        print(f"  no data files found in {data_dir}")
        return
    for path in sorted(files):
        uri = os.path.abspath(path).replace("\\", "/")
        res = cur.execute(
            f"PUT 'file://{uri}' @{STAGE} AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
        ).fetchone()
        print(f"  {os.path.basename(path)} -> {res[6] if res and len(res) > 6 else res}")
    print("\n  staged contents:")
    for row in cur.execute(f"LIST @{STAGE}").fetchall():
        print(f"    {row[0]}  {row[1]} bytes")


def verify(cur):
    print("\n=== row count verification ===")
    ok = True
    for table, expected in EXPECTED_COUNTS.items():
        try:
            actual = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception as exc:
            print(f"  {table:40s} ERROR: {str(exc).splitlines()[0][:60]}")
            ok = False
            continue
        mark = "OK " if actual == expected else "BAD"
        if actual != expected:
            ok = False
        print(f"  {mark} {table:40s} {actual:>10,} (expected {expected:>10,})")
    print("\n  ALL COUNTS MATCH" if ok else "\n  MISMATCH - do not proceed to SPCS")
    return ok


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)

    con, cur = connect()
    try:
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--stage":
                i += 1
                stage_files(cur, args[i] if i < len(args) else "data")
            elif arg == "--verify":
                verify(cur)
            else:
                run_file(con, cur, arg)
            i += 1
    finally:
        con.close()
    print("\nDONE")


if __name__ == "__main__":
    main()


