"""
kafka_to_snowflake.py — Consume 'telemetry' topic, batch-insert into OT.RAW_TELEMETRY.

Spike version: plain connector inserts (proves the pipe). Production upgrade path:
Snowpipe Streaming via the Kafka connector (see docs/BRD.md, out-of-scope note).

Consumer uses manual partition assignment (no consumer group): kafka-python's
group-coordinator path hits a selector bug on Windows (ValueError: Invalid
file descriptor: -1). assign+seek_to_end keeps the same read-from-now behavior
with none of the coordinator machinery.

Credentials via environment variables — never in code:
    $env:SNOWFLAKE_ACCOUNT  = "<account identifier, e.g. DMXGSFN-EYB14592>"
    $env:SNOWFLAKE_USER     = "<username>"
    $env:SNOWFLAKE_PASSWORD = "<password>"

Usage:  python src/kafka_to_snowflake.py
Stop :  Ctrl+C
"""
from __future__ import annotations

import json
import os
import sys
import time

import snowflake.connector
from kafka import KafkaConsumer, TopicPartition

BOOTSTRAP = "localhost:9092"
TOPIC = "telemetry"
BATCH_SIZE = 48          # one full fleet emission
FLUSH_SECONDS = 10       # or flush on timer, whichever first

INSERT_SQL = """
    INSERT INTO OT.RAW_TELEMETRY (asset_id, sensor_type, ts, value, quality_flag)
    VALUES (%(asset_id)s, %(sensor_type)s, %(ts)s, %(value)s, %(quality_flag)s)
"""


def connect() -> snowflake.connector.SnowflakeConnection:
    missing = [k for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")
               if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}")
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse="OEE_WH",
        database="OEE_DB",
        schema="OT",
    )


def main() -> None:
    conn = connect()
    cur = conn.cursor()
    consumer = KafkaConsumer(
        bootstrap_servers=BOOTSTRAP,
        value_deserializer=lambda b: json.loads(b.decode()),
    )
    tp = TopicPartition(TOPIC, 0)
    consumer.assign([tp])
    consumer.seek_to_end(tp)
    print(f"Consuming {TOPIC} -> OT.RAW_TELEMETRY (batch {BATCH_SIZE} / {FLUSH_SECONDS}s)")

    buffer: list[dict] = []
    last_flush = time.time()
    total = 0
    try:
        for msg in consumer:
            buffer.append(msg.value)
            if len(buffer) >= BATCH_SIZE or (time.time() - last_flush) >= FLUSH_SECONDS:
                cur.executemany(INSERT_SQL, buffer)
                conn.commit()
                total += len(buffer)
                print(f"flushed {len(buffer)} rows (total {total})")
                buffer.clear()
                last_flush = time.time()
    except KeyboardInterrupt:
        if buffer:
            cur.executemany(INSERT_SQL, buffer)
            conn.commit()
            total += len(buffer)
        print(f"\nStopped. {total} rows written.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
