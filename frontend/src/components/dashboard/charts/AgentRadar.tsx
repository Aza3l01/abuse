"use client";

import { useState } from "react";

export interface RadarAxis {
  name: string;
  score: number;
  triggered: boolean;
}

const SIZE = 300;
const CENTER = SIZE / 2;
const RADIUS = 96;
const RINGS = [0.25, 0.5, 0.75, 1];

function point(index: number, count: number, value: number): [number, number] {
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / count;
  return [CENTER + Math.cos(angle) * RADIUS * value, CENTER + Math.sin(angle) * RADIUS * value];
}

function ring(count: number, value: number): string {
  return Array.from({ length: count }, (_, i) => point(i, count, value).join(",")).join(" ");
}

/** Radar of per-agent scores (0 to 1). Triggered agents get a filled
 * severity-coloured square, the rest a hollow one. Needs 3 or more axes. */
export function AgentRadar({ axes }: { axes: RadarAxis[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const n = axes.length;
  if (n < 3) return null;

  const shape = axes.map((a, i) => point(i, n, Math.min(1, Math.max(0, a.score))).join(",")).join(" ");
  const active = hover !== null ? axes[hover] : null;

  return (
    <div>
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        style={{ width: "100%", maxWidth: "320px", display: "block", margin: "0 auto" }}
        role="img"
        aria-label="Agent scores radar"
      >
        {RINGS.map(r => (
          <polygon key={r} points={ring(n, r)} style={{ fill: "none", stroke: "var(--color-border)", strokeWidth: 1 }} />
        ))}
        {axes.map((a, i) => {
          const [x, y] = point(i, n, 1);
          return <line key={a.name} x1={CENTER} y1={CENTER} x2={x} y2={y} style={{ stroke: "var(--color-border)", strokeWidth: 1 }} />;
        })}
        <polygon
          points={shape}
          style={{ fill: "var(--color-text)", fillOpacity: 0.1, stroke: "var(--color-text)", strokeWidth: 1.5 }}
        />
        {axes.map((a, i) => {
          const [x, y] = point(i, n, Math.min(1, Math.max(0, a.score)));
          const s = a.triggered ? 9 : 7;
          return (
            <rect
              key={a.name}
              x={x - s / 2}
              y={y - s / 2}
              width={s}
              height={s}
              style={{
                fill: a.triggered ? "var(--color-critical)" : "var(--color-surface)",
                stroke: "var(--color-text)",
                strokeWidth: 1,
              }}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            />
          );
        })}
        {axes.map((a, i) => {
          const [x, y] = point(i, n, 1.2);
          const anchor = Math.abs(x - CENTER) < 6 ? "middle" : x > CENTER ? "start" : "end";
          return (
            <text
              key={`label-${a.name}`}
              x={x}
              y={y}
              textAnchor={anchor}
              dominantBaseline="middle"
              style={{
                fill: a.triggered ? "var(--color-text)" : "var(--color-text-muted)",
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                fontWeight: a.triggered ? 700 : 400,
              }}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            >
              {a.name}
            </text>
          );
        })}
      </svg>
      <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "8px", minHeight: "16px", fontFamily: "var(--font-mono)", textAlign: "center" }}>
        {active
          ? `${active.name}: ${active.score.toFixed(2)}${active.triggered ? ", triggered" : ""}`
          : "Filled marks are triggered agents. Rings are 0.25 to 1.00."}
      </p>
    </div>
  );
}
