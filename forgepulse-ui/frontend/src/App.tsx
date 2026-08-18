// App.tsx — ForgePulse command center shell + screens.
// S1 (Overview) fully built; S2/S3 functional skeletons to grow in G4.
import {
  HashRouter, Routes, Route, NavLink, useParams,
} from "react-router-dom";
import { api, usePolling, Asset, Alert, LineOee, Telemetry } from "./api";
import { useEffect, useState } from "react";

/* ── shared bits ──────────────────────────────────────────────────────── */

function Sparkline({ points, baseline, color }:
  { points: { value: number }[]; baseline: number | null; color: string }) {
  if (!points.length) return null;
  const vals = points.map(p => p.value);
  const lo = Math.min(...vals, baseline ?? Infinity);
  const hi = Math.max(...vals, baseline ?? -Infinity);
  const span = hi - lo || 1;
  const w = 120, h = 28;
  const d = vals.map((v, i) =>
    `${i === 0 ? "M" : "L"}${(i / (vals.length - 1)) * w},${h - ((v - lo) / span) * h}`
  ).join(" ");
  const by = baseline == null ? null : h - ((baseline - lo) / span) * h;
  return (
    <svg width={w} height={h} role="img" aria-label="24h trend">
      {by != null && (
        <line x1="0" y1={by} x2={w} y2={by}
          stroke="var(--text-2)" strokeDasharray="3 3" strokeWidth="1" />
      )}
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

const statusColor = (s: Asset["status"]) => `var(--${s === "sensor-fault" ? "sensor-fault" : s})`;

/* ── S1: Plant Overview ───────────────────────────────────────────────── */

function AssetCard({ a }: { a: Asset }) {
  const [tel, setTel] = useState<Telemetry | null>(null);
  useEffect(() => { api.telemetry(a.asset_id).then(setTel).catch(() => {}); }, [a.asset_id]);
  return (
    <NavLink to={`/triage/${a.asset_id}`}
      className={`panel asset-card ${a.status === "critical" ? "card-critical" : ""}`}
      style={{ display: "block", color: "inherit" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span className="label">{a.asset_id} · {a.line}</span>
        <span className={`label status-${a.status}`}>{a.status}</span>
      </div>
      <div style={{ margin: "6px 0", fontWeight: 500 }}>{a.name}</div>
      {tel && <Sparkline points={tel.points} baseline={tel.baseline}
        color={statusColor(a.status)} />}
      <div className="mono" style={{ marginTop: 6, color: statusColor(a.status) }}>
        health {(a.health * 100).toFixed(0)}%
      </div>
    </NavLink>
  );
}

function Overview() {
  const { data: assets } = usePolling(api.assets);
  const { data: oee } = usePolling(api.oee);
  const { data: alerts } = usePolling(api.alerts);
  const plantOee = oee?.length
    ? oee.reduce((s, l) => s + l.oee, 0) / oee.length : null;
  return (
    <main style={{ padding: 16, display: "grid", gap: 16 }}>
      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8 }}>
        <div className="panel"><div className="label">Plant OEE (7d)</div>
          <div className="kpi-number">{plantOee ? (plantOee * 100).toFixed(1) + "%" : "—"}</div></div>
        {oee?.map(l => (
          <div className="panel" key={l.line}><div className="label">Line {l.line} OEE</div>
            <div className="kpi-number">{(l.oee * 100).toFixed(1)}%</div></div>
        ))}
        <div className="panel"><div className="label">Open alerts</div>
          <div className="kpi-number status-critical">{alerts?.length ?? "—"}</div></div>
      </section>
      <section aria-label="Asset health grid"
        style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
        {assets?.map(a => <AssetCard key={a.asset_id} a={a} />)}
        {!assets && <div className="panel">Loading plant…</div>}
      </section>
    </main>
  );
}

/* ── S2: Triage (skeleton: queue + selected asset chart) ─────────────── */

function Triage() {
  const { assetId } = useParams();
  const { data: alerts } = usePolling(api.alerts);
  const [tel, setTel] = useState<Telemetry | null>(null);
  useEffect(() => {
    if (assetId) api.telemetry(assetId, 72).then(setTel).catch(() => setTel(null));
  }, [assetId]);
  return (
    <main style={{ padding: 16, display: "grid", gridTemplateColumns: "2fr 3fr", gap: 16 }}>
      <section className="panel" aria-label="Alert queue">
        <div className="label" style={{ marginBottom: 8 }}>Alert queue</div>
        {alerts?.length ? alerts.map(al => (
          <NavLink key={al.event_id} to={`/triage/${al.asset_id}`}
            className="panel" style={{ display: "block", marginBottom: 8, color: "inherit" }}>
            <span className={`label status-${al.severity === "HIGH" ? "critical" : "watch"}`}>
              {al.severity}</span>{" "}
            <span className="mono">{al.asset_id}</span> — {al.probable_mode}
          </NavLink>
        )) : <div className="label">No critical alerts — plant nominal</div>}
      </section>
      <section className="panel" aria-label="Investigation">
        <div className="label" style={{ marginBottom: 8 }}>
          {assetId ? `Investigating ${assetId}` : "Select an alert"}
        </div>
        {tel && (
          <Sparkline points={tel.points} baseline={tel.baseline} color="var(--critical)" />
        )}
        {/* G4: full chart, RCA finding card with evidence chips,
            work-order preview + Approve/Edit, NL bar -> agent */}
        <div className="label" style={{ marginTop: 12 }}>
          Finding card, evidence chips, work-order approval and the NL bar land here (G4).
        </div>
      </section>
    </main>
  );
}

/* ── S3: OEE & History (skeleton: per-line table + WO history) ───────── */

function Oee() {
  const { data: oee } = usePolling(api.oee, 30_000);
  const { data: wos } = usePolling(api.workorders, 60_000);
  return (
    <main style={{ padding: 16, display: "grid", gap: 16 }}>
      <section className="panel">
        <div className="label" style={{ marginBottom: 8 }}>OEE by line (7d)</div>
        <table className="mono" style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr className="label">
            <th align="left">Line</th><th>Availability</th><th>Performance</th>
            <th>Quality</th><th>OEE</th></tr></thead>
          <tbody>{oee?.map(l => (
            <tr key={l.line}>
              <td>{l.line}</td><td align="center">{(l.availability * 100).toFixed(1)}%</td>
              <td align="center">{(l.performance * 100).toFixed(1)}%</td>
              <td align="center">{(l.quality * 100).toFixed(1)}%</td>
              <td align="center" style={{ fontWeight: 600 }}>{(l.oee * 100).toFixed(1)}%</td>
            </tr>))}</tbody>
        </table>
      </section>
      <section className="panel">
        <div className="label" style={{ marginBottom: 8 }}>Work order history</div>
        {wos?.map(w => (
          <div key={w.wo_id} style={{ borderBottom: "1px solid var(--border)", padding: "6px 0" }}>
            <span className="mono">{w.wo_id}</span> · {w.asset_id} · {w.type}
            {w.failure_mode && <span className="status-watch"> · {w.failure_mode}</span>}
            <div className="label">{w.notes?.slice(0, 120)}…</div>
          </div>
        ))}
      </section>
    </main>
  );
}

/* ── shell ───────────────────────────────────────────────────────────── */

export default function App() {
  return (
    <HashRouter>
      <header style={{
        display: "flex", gap: 16, alignItems: "baseline",
        padding: "12px 16px", borderBottom: "1px solid var(--border)",
      }}>
        <span className="mono" style={{ fontWeight: 600 }}>FORGEPULSE</span>
        <span className="label">predictive maintenance command center</span>
        <nav style={{ marginLeft: "auto", display: "flex", gap: 12 }}>
          <NavLink to="/">Overview</NavLink>
          <NavLink to="/triage">Triage</NavLink>
          <NavLink to="/oee">OEE</NavLink>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/triage/:assetId?" element={<Triage />} />
        <Route path="/oee" element={<Oee />} />
      </Routes>
    </HashRouter>
  );
}
