"use client";

import { useState } from "react";
import { Group } from "@visx/group";
import { scaleLinear, scaleSqrt, scaleSymlog } from "@visx/scale";
import { AxisBottom, AxisLeft } from "@visx/axis";
import { GridColumns, GridRows } from "@visx/grid";
import { ParentSize } from "@visx/responsive";
import { AXIS_LABEL, AXIS_STROKE, NEUTRAL_MARK, SEV_COLOR, compactNumber } from "./chartTheme";

export interface ScatterPoint {
  id: string;
  label: string;
  x: number;
  /** 0 to 1, drawn as a percentage. */
  y: number;
  /** Optional mark size input. Omit for a fixed size. */
  size?: number;
  severity: string | null;
}

const HEIGHT = 220;
const MARGIN = { top: 10, right: 14, bottom: 34, left: 40 };
const MIN_MARK = 6;
const MAX_MARK = 16;

function Plot({ points, width, xLabel, xScaleType, hover, onHover }: {
  points: ScatterPoint[]; width: number; xLabel: string; xScaleType: "linear" | "symlog";
  hover: string | null; onHover: (id: string | null) => void;
}) {
  const innerW = Math.max(0, width - MARGIN.left - MARGIN.right);
  const innerH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const maxX = Math.max(1, ...points.map(p => p.x));
  const xDomain: [number, number] = [0, maxX];
  const xScale = xScaleType === "symlog"
    ? scaleSymlog<number>({ domain: xDomain, range: [0, innerW], nice: true })
    : scaleLinear<number>({ domain: xDomain, range: [0, innerW], nice: true });
  // Symlog ticks from the default generator bunch up at the high end, so use
  // powers of ten instead.
  const xTicks = xScaleType === "symlog"
    ? [0, ...[1, 2, 3, 4, 5, 6, 7, 8].map(e => 10 ** e).filter(v => v <= xScale.domain()[1])]
    : undefined;
  const yScale = scaleLinear<number>({ domain: [0, 1], range: [innerH, 0] });
  const maxSize = Math.max(1, ...points.map(p => p.size ?? 0));
  const sizeScale = scaleSqrt<number>({ domain: [0, maxSize], range: [MIN_MARK, MAX_MARK] });
  const markSize = (p: ScatterPoint) => (p.size === undefined ? 9 : sizeScale(p.size));

  return (
    <svg width={width} height={HEIGHT} role="img" aria-label={`Risk score against ${xLabel}`}>
      <Group left={MARGIN.left} top={MARGIN.top}>
        <GridRows scale={yScale} width={innerW} stroke={AXIS_STROKE} tickValues={[0, 0.25, 0.5, 0.75, 1]} />
        <GridColumns scale={xScale} height={innerH} stroke={AXIS_STROKE} numTicks={5} tickValues={xTicks} />
        {/* Hovered mark is drawn last so it is never hidden under a neighbour. */}
        {[...points].sort((a, b) => (a.id === hover ? 1 : 0) - (b.id === hover ? 1 : 0)).map(p => {
          const s = markSize(p);
          return (
            <rect
              key={p.id}
              x={xScale(p.x) - s / 2}
              y={yScale(p.y) - s / 2}
              width={s}
              height={s}
              style={{
                fill: p.severity ? SEV_COLOR[p.severity] ?? NEUTRAL_MARK : NEUTRAL_MARK,
                fillOpacity: 0.85,
                stroke: hover === p.id ? "var(--color-text)" : "var(--color-surface)",
                strokeWidth: hover === p.id ? 2 : 1,
              }}
              onMouseEnter={() => onHover(p.id)}
              onMouseLeave={() => onHover(null)}
            />
          );
        })}
        <AxisLeft
          scale={yScale}
          tickValues={[0, 0.25, 0.5, 0.75, 1]}
          stroke={AXIS_STROKE}
          tickStroke={AXIS_STROKE}
          tickFormat={v => `${Math.round(Number(v) * 100)}`}
          tickLabelProps={() => ({ ...AXIS_LABEL, textAnchor: "end", dx: "-0.25em", dy: "0.3em" })}
        />
        <AxisBottom
          top={innerH}
          scale={xScale}
          numTicks={5}
          tickValues={xTicks}
          stroke={AXIS_STROKE}
          tickStroke={AXIS_STROKE}
          tickFormat={v => compactNumber(Number(v))}
          label={`${xLabel}${xScaleType === "symlog" ? " (log scale)" : ""}`}
          labelProps={{ ...AXIS_LABEL, textAnchor: "middle", dy: "-0.2em" }}
          tickLabelProps={() => ({ ...AXIS_LABEL, textAnchor: "middle" })}
        />
      </Group>
    </svg>
  );
}

/** Risk score (0 to 100, vertical) against a request count (horizontal).
 * Square marks coloured by severity. Mark size follows `size` when given. */
export function RiskScatter({ points, xLabel, xScaleType = "linear", caption }: {
  points: ScatterPoint[]; xLabel: string; xScaleType?: "linear" | "symlog"; caption?: string;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const hovered = points.find(p => p.id === hover) ?? null;

  return (
    <div>
      <div style={{ width: "100%", height: HEIGHT }}>
        <ParentSize>
          {({ width }) =>
            width > 0 ? (
              <Plot points={points} width={width} xLabel={xLabel} xScaleType={xScaleType} hover={hover} onHover={setHover} />
            ) : null
          }
        </ParentSize>
      </div>
      <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "8px", minHeight: "16px", fontFamily: "var(--font-mono)" }}>
        {hovered
          ? `${hovered.label}: risk ${Math.round(hovered.y * 100)}%, ${hovered.x.toLocaleString()} ${xLabel.toLowerCase()}${hovered.size !== undefined ? `, ${hovered.size.toLocaleString()} threats` : ""}`
          : caption ?? "Hover a mark for the IP."}
      </p>
    </div>
  );
}
