// LiveMonitor.tsx — Sentinel-style live sensor feed, per motor.
// Save as src/screens/LiveMonitor.tsx; add route + nav link in App.tsx:
//   <Route path="/live/:assetId?" element={<LiveMonitor />} />
//   <NavLink to="/live">Live</NavLink>
import { useEffect, useState } from "react";
import { useParams, NavLink } from "react-router-dom";
import { api, Asset } from "../api";

const SENSORS = [
  { key: "VIBRATION_RMS", label: "Vibration (mm/s)" },
  { key: "BEARING_TEMP", label: "Temp (°C)" },
  { key: "RPM", label: "RPM" },
  { key: "CURRENT_DRAW", label: "Current (A)" },
];

interface Live {
  baseline: number; points: number[];
  anomaly: { start: number; end: number; label: string }[];
  stats: { rms: number; peak: number; avg: number };
}

export default function LiveMonitor() {
  const { assetId = "AST-007" } = useParams();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [sensor, setSensor] = useState(SENSORS[0].key);
  const [live, setLive] = useState<Live | null>(null);

  useEffect(() => { api.assets().then(setAssets).catch(() => {}); }, []);
  useEffect(() => {
    let on = true;
    const tick = () =>
      fetch(`/api/live/${assetId}?sensor=${sensor}`)
        .then(r => r.json()).then(d => on && setLive(d)).catch(() => {});
    tick();
    const t = setInterval(tick, 2000);
    return () => { on = false; clearInterval(t); };
  }, [assetId, sensor]);

  const W = 1000, H = 320;
  let path = "", band = null as null | { x: number; w: number; label: string };
  if (live?.points.length) {
    const vals = live.points;
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const span = hi - lo || 1;
    path = vals.map((v, i) =>
      `${i ? "L" : "M"}${(i / (vals.length - 1)) * W},${H - ((v - lo) / span) * (H - 20) - 10}`
    ).join(" ");
    const a = live.anomaly[0];
    if (a) band = {
      x: (a.start / vals.length) * W,
      w: ((a.end - a.start) / vals.length) * W, label: a.label,
    };
  }

  return (
    <main style={{ padding: 16, display: "grid", gap: 12 }}>
      {/* motor selector */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {assets.map(a => (
          <NavLink key={a.asset_id} to={`/live/${a.asset_id}`}>
            <button className={a.asset_id === assetId ? "primary" : ""}
              style={a.status === "critical"
                ? { borderColor: "var(--critical)" } : {}}>
              {a.asset_id}
            </button>
          </NavLink>
        ))}
      </div>

      {/* sensor tabs + live badge */}
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {SENSORS.map(s => (
          <button key={s.key} className={s.key === sensor ? "primary" : ""}
            onClick={() => setSensor(s.key)}>{s.label}</button>
        ))}
        <span className="label" style={{
          marginLeft: "auto", color: "var(--healthy)",
          border: "1px solid var(--healthy)", borderRadius: 12, padding: "2px 10px",
        }}>REAL-TIME</span>
      </div>

      {/* waveform */}
      <div className="panel" style={{ padding: 8 }}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
          aria-label={`Live ${sensor} for ${assetId}`}>
          {/* grid */}
          {[...Array(9)].map((_, i) => (
            <line key={i} x1={0} x2={W} y1={(i + 1) * H / 10}
              y2={(i + 1) * H / 10} stroke="var(--border)" strokeWidth="0.5" />
          ))}
          {/* anomaly band */}
          {band && (
            <g>
              <rect x={band.x} y={0} width={band.w} height={H}
                fill="var(--critical)" opacity="0.12"
                stroke="var(--critical)" strokeDasharray="4 4" />
              <rect x={band.x} y={6} width={Math.max(band.w, 260)} height={26}
                fill="var(--critical)" rx="4" />
              <text x={band.x + 10} y={24} fill="#fff" fontSize="13"
                fontFamily="Inter, sans-serif" fontWeight="600">
                ⚠ {band.label}
              </text>
            </g>
          )}
          <path d={path} fill="none" stroke="var(--accent)" strokeWidth="1.4" />
          {band && (
            <clipPath id="anom"><rect x={band.x} y={0} width={band.w} height={H} /></clipPath>
          )}
          {band && (
            <path d={path} fill="none" stroke="var(--critical)"
              strokeWidth="1.8" clipPath="url(#anom)" />
          )}
        </svg>
      </div>

      {/* stat cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8 }}>
        {live && ([
          ["RMS", live.stats.rms], ["PEAK", live.stats.peak],
          ["AVG", live.stats.avg], ["BASELINE", live.baseline.toFixed(2)],
        ] as const).map(([k, v]) => (
          <div className="panel" key={k}>
            <div className="label">{k}</div>
            <div className="kpi-number">{v}</div>
          </div>
        ))}
      </div>
    </main>
  );
}
