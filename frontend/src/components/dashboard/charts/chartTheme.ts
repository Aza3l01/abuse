// Shared helpers for the visx dashboard charts. Square marks, hard 1px
// borders, no gradients, no shadows (see frontend/DESIGN_SYSTEM.md). Severity
// colours are the functional product colours, never brand colours.

export type Severity = "critical" | "high" | "medium" | "low";

export const SEVERITIES: readonly Severity[] = ["critical", "high", "medium", "low"];

export const SEV_COLOR: Record<string, string> = {
  critical: "var(--color-critical)",
  high:     "var(--color-high)",
  medium:   "var(--color-medium)",
  low:      "var(--color-low)",
};

export const NEUTRAL_MARK = "var(--color-text-muted)";

export const AXIS_STROKE = "var(--color-border)";

export const AXIS_LABEL = {
  fill: "var(--color-text-muted)",
  fontSize: 10,
  fontFamily: "var(--font-mono)",
} as const;

export function compactNumber(n: number): string {
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}
