"""
kafka_producer.py — Live telemetry feed to Kafka topic 'telemetry'.

Emits one reading per asset per sensor every EMIT_INTERVAL seconds,
continuing each asset's baseline behavior — and continuing AST-007's
active bearing-wear ramp so the live feed matches the loaded history.

Usage:  python src/kafka_producer.py
Stop :  Ctrl+C
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
from kafka import KafkaProducer

BOOTSTRAP = "localhost:9092"
TOPIC = "telemetry"
EMIT_INTERVAL = 5  # seconds between full-fleet emissions (accelerated vs 5-min real cadence)

# asset_id: (vib_base, temp_base, rpm_base, amp_base)
FLEET = {
    "AST-001": (2.1, 62.0, 1480, 42.0), "AST-002": (2.8, 55.0, 2900, 18.5),
    "AST-003": (3.2, 71.0, 2950, 55.0), "AST-004": (1.9, 58.0, 960, 12.0),
    "AST-005": (2.0, 61.0, 1480, 41.5), "AST-006": (3.0, 64.0, 1800, 27.0),
    "AST-007": (3.4, 72.5, 2950, 56.0), "AST-008": (2.2, 54.0, 1440, 9.5),
    "AST-009": (2.3, 63.5, 1475, 48.0), "AST-010": (2.9, 57.0, 2900, 21.0),
    "AST-011": (3.1, 68.0, 2900, 52.0), "AST-012": (2.4, 59.0, 720, 14.0),
}

# AST-007 live state: history ended ~3.1x baseline and climbing.
# Continue the ramp slowly per emission so the dashboard visibly worsens.
AST7_VIB_MULT = 3.1
AST7_TEMP_ADD = 10.0
RAMP_PER_EMIT = 0.002  # multiplier growth per emission


def readings(rng: np.random.Generator) -> list[dict]:
    global AST7_VIB_MULT, AST7_TEMP_ADD
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    out = []
    for asset, (vib, temp, rpm, amp) in FLEET.items():
        v, t = vib, temp
        if asset == "AST-007":
            AST7_VIB_MULT += RAMP_PER_EMIT
            AST7_TEMP_ADD += RAMP_PER_EMIT * 2
            v = vib * AST7_VIB_MULT
            t = temp + AST7_TEMP_ADD
        for sensor, base, noise in (
            ("VIBRATION_RMS", v if asset == "AST-007" else vib, 0.08 * vib),
            ("BEARING_TEMP", t if asset == "AST-007" else temp, 0.9),
            ("RPM", rpm, 0.004 * rpm),
            ("CURRENT_DRAW", amp, 0.03 * amp),
        ):
            out.append({
                "asset_id": asset,
                "sensor_type": sensor,
                "ts": ts,
                "value": round(float(base + rng.normal(0, noise)), 3),
                "quality_flag": "GOOD",
            })
    return out


def main() -> None:
    rng = np.random.default_rng()
    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        value_serializer=lambda d: json.dumps(d).encode(),
    )
    print(f"Producing to {TOPIC} @ {BOOTSTRAP} every {EMIT_INTERVAL}s. Ctrl+C to stop.")
    n = 0
    try:
        while True:
            batch = readings(rng)
            for msg in batch:
                producer.send(TOPIC, msg)
            producer.flush()
            n += len(batch)
            a7 = next(m for m in batch
                      if m["asset_id"] == "AST-007" and m["sensor_type"] == "VIBRATION_RMS")
            print(f"sent {len(batch)} (total {n}) | AST-007 vib now {a7['value']} mm/s")
            time.sleep(EMIT_INTERVAL)
    except KeyboardInterrupt:
        print(f"\nStopped. {n} messages sent.")


if __name__ == "__main__":
    main()
