"use client";

import { useState } from "react";
import { Group } from "@visx/group";
import { scaleLinear, scalePoint } from "@visx/scale";
import { AxisBottom, AxisLeft } from "@visx/axis";
import { LinePath } from "@visx/shape";
import { GridRows } from "@visx/grid";
import { ParentSize } from "@visx/responsive";
import { AXIS_LABEL, AXIS_STROKE, SEV_COLOR, SEVERITIES, compactNumber, type Severity } from "./chartTheme";

export interface TrendDay {
  date: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

const HEIGHT = 220;
const MARGIN = { top: 8, right: 12, bottom: 40, left: 36 };
const MARKER = 6;
// Draw low first so critical ends up on top where lines overlap.
const DRAW_ORDER: readonly Severity[] = ["low", "medium", "high", "critical"];
// Up to this many points every day gets a square marker, beyond it only the hovered day does.
const MARKER_ALL_MAX = 10;

function dayTotal(d: TrendDay): number {
  return SEVERITIES.reduce((sum, k) => sum + (d[k] || 0), 0);
}

function Lines({ trend, width, hover, onHover }: {
  trend: TrendDay[]; width: number; hover: number | null; onHover: (i: number | null) => void;
}) {
  const innerW = Math.max(0, width - MARGIN.left - MARGIN.right);
  const innerH = HEIGHT - MARGIN.top - MARGIN.bottom;

  const xScale = scalePoint<string>({ domain: trend.map(d => d.date), range: [0, innerW] });
  const maxCount = Math.max(1, ...trend.flatMap(d => SEVERITIES.map(s => d[s] || 0)));
  const yScale = scaleLinear<number>({ domain: [0, maxCount], range: [innerH, 0], nice: true });

  const first = trend[0].date;
  const last = trend[trend.length - 1].date;
  const edgeDates = first === last ? [first] : [first, last];
  const showAllMarkers = trend.length <= MARKER_ALL_MAX;
  const hoverX = hover !== null ? xScale(trend[hover].date) ?? 0 : 0;

  return (
    <svg width={width} height={HEIGHT} role="img" aria-label="Threats per day by severity">
      <Group left={MARGIN.left} top={MARGIN.top}>
        <GridRows scale={yScale} width={innerW} stroke={AXIS_STROKE} numTicks={Math.min(4, maxCount)} />
        {DRAW_ORDER.map(sev => (
          <LinePath<TrendDay>
            key={sev}
            data={trend}
            x={d => xScale(d.date) ?? 0}
            y={d => yScale(d[sev] || 0)}
            style={{ stroke: SEV_COLOR[sev], strokeWidth: 2, fill: "none", strokeLinejoin: "miter" }}
          />
        ))}
        {(showAllMarkers ? trend.map((_, i) => i) : hover !== null ? [hover] : []).flatMap(i =>
          DRAW_ORDER.map(sev => (
            <rect
              key={`${i}-${sev}`}
              x={(xScale(trend[i].date) ?? 0) - MARKER / 2}
              y={yScale(trend[i][sev] || 0) - MARKER / 2}
              width={MARKER}
              height={MARKER}
              style={{ fill: SEV_COLOR[sev] }}
            />
          )),
        )}
        {hover !== null && (
          <line x1={hoverX} x2={hoverX} y1={0} y2={innerH} style={{ stroke: "var(--color-text)", strokeWidth: 1 }} />
        )}
        <rect
          x={0} y={0} width={innerW} height={innerH}
          style={{ fill: "transparent" }}
          onMouseMove={e => {
            const box = e.currentTarget.getBoundingClientRect();
            const frac = box.width > 0 ? (e.clientX - box.left) / box.width : 0;
            const i = Math.round(frac * (trend.length - 1));
            onHover(Math.min(trend.length - 1, Math.max(0, i)));
          }}
          onMouseLeave={() => onHover(null)}
        />
        <AxisLeft
          scale={yScale}
          numTicks={Math.min(4, maxCount)}
          stroke={AXIS_STROKE}
          tickStroke={AXIS_STROKE}
          tickFormat={v => compactNumber(Number(v))}
          tickLabelProps={() => ({ ...AXIS_LABEL, textAnchor: "end", dx: "-0.25em", dy: "0.3em" })}
        />
        <AxisBottom
          top={innerH}
          scale={xScale}
          tickValues={edgeDates}
          stroke={AXIS_STROKE}
          tickStroke={AXIS_STROKE}
          tickFormat={d => String(d)}
          tickLabelProps={(value) => ({
            ...AXIS_LABEL,
            textAnchor: edgeDates.length > 1 && value === last ? "end" : edgeDates.length > 1 ? "start" : "middle",
          })}
          label="Date"
          labelProps={{ ...AXIS_LABEL, textAnchor: "middle", dy: "0.5em" }}
          labelOffset={4}
        />
      </Group>
    </svg>
  );
}

export function TrendLines({ trend }: { trend: TrendDay[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!trend.length) return null;

  const day = hover !== null ? trend[hover] : null;

  return (
    <div>
      <div style={{ width: "100%", height: HEIGHT }}>
        <ParentSize>
          {({ width }) => (width > 0 ? <Lines trend={trend} width={width} hover={hover} onHover={setHover} /> : null)}
        </ParentSize>
      </div>
      {/* Readout line. Two lines tall so a long breakdown never shifts the layout. */}
      <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "8px", minHeight: "34px", lineHeight: 1.5, fontFamily: "var(--font-mono)" }}>
        {day
          ? `${day.date}: ${dayTotal(day)} total, ${SEVERITIES.map(s => `${day[s] || 0} ${s}`).join(", ")}`
          : "Hover the chart for the date and daily breakdown."}
      </p>
      <div style={{ display: "flex", gap: "12px", marginTop: "8px" }}>
        {SEVERITIES.map(sev => (
          <div key={sev} style={{ display: "flex", alignItems: "center", gap: "4px" }}>
            <span style={{ width: "8px", height: "8px", background: SEV_COLOR[sev], display: "inline-block" }} />
            <span style={{ fontSize: "10px", color: "var(--color-text-muted)", textTransform: "capitalize" }}>{sev}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
