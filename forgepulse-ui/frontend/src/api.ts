// api.ts — typed client for the ForgePulse API contract.
// Same endpoints in dev (mock backend) and prod (SPCS FastAPI).
import { useEffect, useState } from "react";

export interface Asset {
  asset_id: string; name: string; type: string; line: string;
  criticality: "HIGH" | "MEDIUM" | "LOW";
  health: number; status: "healthy" | "watch" | "critical" | "sensor-fault";
}
export interface TelemetryPoint { ts: string; value: number; }
export interface Telemetry {
  asset_id: string; sensor: string; baseline: number | null;
  points: TelemetryPoint[];
}
export interface Alert {
  event_id: number; asset_id: string; probable_mode: string;
  severity: "HIGH" | "MEDIUM" | "LOW"; score: number; status: string;
  detected_ts: string; days_to_threshold: number | null;
}
export interface LineOee {
  line: string; availability: number; performance: number;
  quality: number; oee: number;
}
export interface WorkOrder {
  wo_id: string; asset_id: string; type: string; opened: string;
  failure_mode: string | null; downtime_hours: number; notes: string;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export const api = {
  assets: () => get<Asset[]>("/api/assets"),
  telemetry: (id: string, hours = 24) =>
    get<Telemetry>(`/api/telemetry/${id}?hours=${hours}`),
  alerts: () => get<Alert[]>("/api/alerts"),
  oee: () => get<LineOee[]>("/api/oee"),
  workorders: () => get<WorkOrder[]>("/api/workorders"),
};

/** Poll an endpoint on an interval (BRD §8.3: 60s S1/S2). */
export function usePolling<T>(fn: () => Promise<T>, ms = 60_000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const tick = () =>
      fn().then(d => live && (setData(d), setError(null)))
          .catch(e => live && setError(String(e)));
    tick();
    const t = setInterval(tick, ms);
    return () => { live = false; clearInterval(t); };
  }, []);
  return { data, error };
}
