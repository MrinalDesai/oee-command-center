// PipelineFlow.tsx — glowing pipeline flowchart for one fault event.
// Stages light up as the event traverses: DETECT -> DIAGNOSE -> ACT.
// Drop into src/components/, then in Triage:
//   import { PipelineFlow } from "../components/PipelineFlow";
//   <PipelineFlow status={alert.status} />
import React from "react";

const STAGES = ["DETECT", "DIAGNOSE", "ACT", "WORK ORDER"] as const;

function stageIndex(status: string): number {
  switch (status) {
    case "NEW": return 0;
    case "INVESTIGATING": return 1;
    case "ACTIONED": return 3;
    case "DISMISSED": return 1;
    default: return 0;
  }
}

export function PipelineFlow({ status }: { status: string }) {
  const active = stageIndex(status);
  const W = 640, H = 96, boxW = 120, boxH = 44, gap = (W - 4 * boxW) / 3;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
      aria-label={`Pipeline status: ${status}`}>
      <defs>
        <filter id="glow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge>
            <feMergeNode in="b" /><feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <style>{`
          .flow-edge { stroke-dasharray: 6 6; animation: flow 1s linear infinite; }
          @keyframes flow { to { stroke-dashoffset: -12; } }
          .node-current { animation: nodepulse 2s ease-in-out infinite; }
          @keyframes nodepulse { 0%,100%{opacity:1} 50%{opacity:.75} }
          @media (prefers-reduced-motion: reduce) {
            .flow-edge, .node-current { animation: none; }
          }
        `}</style>
      </defs>

      {STAGES.map((label, i) => {
        const x = i * (boxW + gap), y = (H - boxH) / 2;
        const done = i < active, current = i === active;
        const color = done ? "var(--healthy)"
          : current ? (status === "DISMISSED" ? "var(--text-2)" : "var(--critical)")
          : "var(--border)";
        return (
          <g key={label}>
            {i > 0 && (
              <line className={i <= active ? "flow-edge" : undefined}
                x1={x - gap} y1={H / 2} x2={x} y2={H / 2}
                stroke={i <= active ? "var(--accent)" : "var(--border)"}
                strokeWidth="2"
                filter={i <= active ? "url(#glow)" : undefined} />
            )}
            <rect className={current ? "node-current" : undefined}
              x={x} y={y} width={boxW} height={boxH} rx="8"
              fill="var(--panel)" stroke={color} strokeWidth="2"
              filter={done || current ? "url(#glow)" : undefined} />
            <text x={x + boxW / 2} y={H / 2 + 4} textAnchor="middle"
              fill={done || current ? "var(--text)" : "var(--text-2)"}
              fontFamily="JetBrains Mono, monospace" fontSize="12">
              {label}
            </text>
            {done && (
              <text x={x + boxW - 14} y={y + 14} fill="var(--healthy)"
                fontSize="11" filter="url(#glow)">✓</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
