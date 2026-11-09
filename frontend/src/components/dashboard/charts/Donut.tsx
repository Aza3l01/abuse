"use client";

import { useState } from "react";
import { Group } from "@visx/group";
import { Pie } from "@visx/shape";

export interface DonutSlice {
  key: string;
  label: string;
  value: number;
  color: string;
}

const SIZE = 150;
const THICKNESS = 22;

export function Donut({ slices, centerLabel }: { slices: DonutSlice[]; centerLabel: string }) {
  const [active, setActive] = useState<string | null>(null);
  const total = slices.reduce((s, d) => s + d.value, 0);
  const radius = SIZE / 2;
  const shown = slices.filter(s => s.value > 0);
  const activeSlice = slices.find(s => s.key === active) ?? null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "20px", flexWrap: "wrap" }}>
      <svg width={SIZE} height={SIZE} role="img" aria-label={`${centerLabel}: ${total} total`}>
        <Group top={radius} left={radius}>
          {total === 0 ? (
            <circle r={radius - THICKNESS / 2} fill="none" strokeWidth={THICKNESS} style={{ stroke: "var(--color-border)" }} />
          ) : (
            <Pie
              data={shown}
              pieValue={d => d.value}
              pieSort={null}
              outerRadius={radius}
              innerRadius={radius - THICKNESS}
              padAngle={0}
            >
              {pie =>
                pie.arcs.map(arc => (
                  <path
                    key={arc.data.key}
                    d={pie.path(arc) ?? undefined}
                    style={{
                      fill: arc.data.color,
                      stroke: "var(--color-surface)",
                      strokeWidth: 1,
                      opacity: active && active !== arc.data.key ? 0.35 : 1,
                    }}
                    onMouseEnter={() => setActive(arc.data.key)}
                    onMouseLeave={() => setActive(null)}
                  />
                ))
              }
            </Pie>
          )}
          <text textAnchor="middle" y={-2} style={{ fill: "var(--color-text)", fontSize: 22, fontWeight: 700 }}>
            {(activeSlice ? activeSlice.value : total).toLocaleString()}
          </text>
          <text textAnchor="middle" y={14} style={{ fill: "var(--color-text-muted)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            {activeSlice ? activeSlice.label : centerLabel}
          </text>
        </Group>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        {slices.map(s => (
          <div
            key={s.key}
            onMouseEnter={() => setActive(s.key)}
            onMouseLeave={() => setActive(null)}
            style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px" }}
          >
            <span style={{ width: "8px", height: "8px", background: s.color, display: "inline-block", flexShrink: 0 }} />
            <span style={{ color: "var(--color-text-muted)", minWidth: "64px" }}>{s.label}</span>
            <span style={{ fontFamily: "var(--font-mono)" }}>{s.value.toLocaleString()}</span>
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text-muted)" }}>
              {total > 0 ? `${Math.round((s.value / total) * 100)}%` : "0%"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
