"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { API_URL } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TrendDay {
  date: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

interface TopIp {
  ip: string;
  count: number;
  risk_score: number;
}

interface Summary {
  period_days: number;
  total_threats: number;
  new_threats_today: number;
  by_severity: { critical: number; high: number; medium: number; low: number };
  top_ips: TopIp[];
  cost_prevented: number;
  ips_flagged: number;
  trend: TrendDay[];
}

interface Verdict {
  id: string;
  timestamp: string;
  ip: string;
  method: string | null;
  endpoint: string | null;
  threat_type: string | null;
  severity: string;
  confidence: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SEV_COLOR: Record<string, string> = {
  critical: "var(--color-critical)",
  high:     "var(--color-high)",
  medium:   "var(--color-medium)",
  low:      "var(--color-low)",
};

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span style={{
      display: "inline-block",
      padding: "2px 6px",
      fontSize: "10px",
      fontWeight: 600,
      letterSpacing: "0.06em",
      textTransform: "uppercase",
      color: "#fff",
      background: SEV_COLOR[severity] ?? "#888",
    }}>
      {severity}
    </span>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{
      border: "1px solid var(--color-border)",
      background: "var(--color-surface)",
      padding: "20px",
      flex: "1 1 0",
      minWidth: 0,
    }}>
      <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--color-text-muted)", marginBottom: "8px" }}>
        {label}
      </p>
      <p style={{ fontSize: "28px", fontWeight: 700, lineHeight: 1, marginBottom: sub ? "4px" : 0 }}>
        {value}
      </p>
      {sub && (
        <p style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>{sub}</p>
      )}
    </div>
  );
}

// Inline SVG stacked bar chart — no external dependency
function TrendChart({ trend }: { trend: TrendDay[] }) {
  if (!trend.length) return null;

  const W = 420;
  const H = 80;
  const slotW = W / trend.length;
  const barW = slotW * 0.6;
  const barOffset = slotW * 0.2;
  const SEV_ORDER = ["low", "medium", "high", "critical"] as const;
  const COLORS = { critical: "#E53E3E", high: "#DD6B20", medium: "#D69E2E", low: "#38A169" };
  const maxTotal = Math.max(1, ...trend.map(d =>
    SEV_ORDER.reduce((s, k) => s + (d[k] || 0), 0)
  ));

  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {trend.map((day, i) => {
        const barX = i * slotW + barOffset;
        let yBottom = H;
        return (
          <g key={day.date}>
            {SEV_ORDER.map(sev => {
              const count = day[sev] || 0;
              if (!count) return null;
              const barH = Math.max(1, (count / maxTotal) * H);
              yBottom -= barH;
              return (
                <rect
                  key={sev}
                  x={barX}
                  y={yBottom}
                  width={barW}
                  height={barH}
                  fill={COLORS[sev]}
                />
              );
            })}
            <text
              x={i * slotW + slotW / 2}
              y={H + 14}
              textAnchor="middle"
              fontSize="9"
              fill="var(--color-text-muted)"
            >
              {day.date.slice(5)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardOverview() {
  const router = useRouter();
  const [days,     setDays]     = useState(7);
  const [summary,  setSummary]  = useState<Summary | null>(null);
  const [recent,   setRecent]   = useState<Verdict[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);

    Promise.all([
      fetch(`${API_URL}/dashboard/summary?days=${days}`, { credentials: "include" }),
      fetch(`${API_URL}/verdicts?limit=10`,              { credentials: "include" }),
    ])
      .then(async ([sr, vr]) => {
        if (sr.status === 401 || vr.status === 401) { router.push("/login"); return; }
        if (!sr.ok || !vr.ok) throw new Error("API error");
        const [s, v] = await Promise.all([sr.json(), vr.json()]);
        setSummary(s);
        setRecent(v.items ?? []);
      })
      .catch(() => setError("Failed to load dashboard data."))
      .finally(() => setLoading(false));
  }, [days, router]);

  if (loading) {
    return (
      <div style={{ padding: "48px 32px", color: "var(--color-text-muted)", fontSize: "13px" }}>
        Loading…
      </div>
    );
  }
  if (error || !summary) {
    return (
      <div style={{ padding: "48px 32px", color: "var(--color-text-muted)", fontSize: "13px" }}>
        {error ?? "No data"}
      </div>
    );
  }

  const s = summary;

  return (
    <main style={{ padding: "32px", width: "100%" }}>

      {/* Title + period selector */}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: "28px" }}>
        <h1 style={{ fontFamily: "var(--font-brand)", fontSize: "22px", fontWeight: 700 }}>
          Overview
        </h1>
        <div style={{ display: "flex", gap: "4px" }}>
          {[7, 30].map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              style={{
                padding: "4px 12px",
                fontSize: "12px",
                border: "1px solid var(--color-border)",
                background: days === d ? "var(--color-text)" : "transparent",
                color:      days === d ? "var(--color-bg)"   : "var(--color-text-muted)",
                cursor: "pointer",
              }}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Stat cards */}
      <div style={{ display: "flex", gap: "12px", marginBottom: "28px" }}>
        <StatCard
          label="Total threats"
          value={s.total_threats.toLocaleString()}
          sub={`+${s.new_threats_today} today`}
        />
        <StatCard
          label="Critical"
          value={s.by_severity.critical.toLocaleString()}
        />
        <StatCard
          label="IPs flagged"
          value={s.ips_flagged.toLocaleString()}
        />
        <StatCard
          label="Cost prevented"
          value={`$${s.cost_prevented.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
        />
      </div>

      {/* Trend chart + top IPs */}
      <div style={{ display: "flex", gap: "12px", marginBottom: "28px" }}>
        {/* Chart */}
        <div style={{
          flex: "2 1 0",
          border: "1px solid var(--color-border)",
          background: "var(--color-surface)",
          padding: "20px",
        }}>
          <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--color-text-muted)", marginBottom: "16px" }}>
            Threat trend — {days}d
          </p>
          {s.trend.every(d => d.critical + d.high + d.medium + d.low === 0) ? (
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)", padding: "24px 0", textAlign: "center" }}>
              No threats detected in this period
            </p>
          ) : (
            <>
              <TrendChart trend={s.trend} />
              {/* Legend */}
              <div style={{ display: "flex", gap: "12px", marginTop: "12px" }}>
                {(["critical", "high", "medium", "low"] as const).map(sev => (
                  <div key={sev} style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    <span style={{ width: "8px", height: "8px", background: SEV_COLOR[sev], display: "inline-block" }} />
                    <span style={{ fontSize: "10px", color: "var(--color-text-muted)", textTransform: "capitalize" }}>{sev}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Top IPs */}
        <div style={{
          flex: "1 1 0",
          border: "1px solid var(--color-border)",
          background: "var(--color-surface)",
          padding: "20px",
        }}>
          <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--color-text-muted)", marginBottom: "16px" }}>
            Top threat IPs
          </p>
          {s.top_ips.length === 0 ? (
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>No data</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              {s.top_ips.map(tip => (
                <Link
                  key={tip.ip}
                  href={`/dashboard/alerts?ip=${tip.ip}`}
                  style={{ textDecoration: "none", color: "inherit" }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px" }}>{tip.ip}</span>
                    <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
                      {tip.count} hits · {(tip.risk_score * 100).toFixed(0)}%
                    </span>
                  </div>
                  {/* Risk bar */}
                  <div style={{ height: "2px", background: "var(--color-border)", marginTop: "4px" }}>
                    <div style={{
                      height: "100%",
                      width: `${(tip.risk_score * 100).toFixed(0)}%`,
                      background: tip.risk_score >= 0.8 ? SEV_COLOR.critical
                                : tip.risk_score >= 0.6 ? SEV_COLOR.high
                                : tip.risk_score >= 0.4 ? SEV_COLOR.medium
                                : SEV_COLOR.low,
                    }} />
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Recent verdicts */}
      <div style={{
        border: "1px solid var(--color-border)",
        background: "var(--color-surface)",
      }}>
        <div style={{
          padding: "16px 20px",
          borderBottom: "1px solid var(--color-border)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}>
          <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--color-text-muted)" }}>
            Recent threats
          </p>
          <Link href="/dashboard/alerts" style={{ fontSize: "12px", color: "var(--color-text-muted)", textDecoration: "none" }}>
            View all →
          </Link>
        </div>
        {recent.length === 0 ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>
            No threats detected yet. Once your S3 logs are processed, detections appear here.
          </p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr>
                {["Time", "IP", "Method", "Endpoint", "Threat", "Severity", "Confidence"].map(h => (
                  <th key={h} style={{
                    padding: "10px 20px",
                    textAlign: "left",
                    fontSize: "11px",
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                    color: "var(--color-text-muted)",
                    borderBottom: "1px solid var(--color-border)",
                    fontWeight: 500,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {recent.map(v => (
                <tr key={v.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                  <td style={{ padding: "10px 20px", color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>
                    {fmtTime(v.timestamp)}
                  </td>
                  <td style={{ padding: "10px 20px" }}>
                    <Link href={`/dashboard/alerts?ip=${v.ip}`} style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: "inherit", textDecoration: "none" }}>
                      {v.ip}
                    </Link>
                  </td>
                  <td style={{ padding: "10px 20px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", fontSize: "12px" }}>
                    {v.method ?? "—"}
                  </td>
                  <td style={{ padding: "10px 20px", maxWidth: "200px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {v.endpoint ?? "—"}
                  </td>
                  <td style={{ padding: "10px 20px", color: "var(--color-text-muted)" }}>
                    {v.threat_type ?? "—"}
                  </td>
                  <td style={{ padding: "10px 20px" }}>
                    <SeverityBadge severity={v.severity} />
                  </td>
                  <td style={{ padding: "10px 20px", fontFamily: "var(--font-mono)", fontSize: "12px" }}>
                    {(v.confidence * 100).toFixed(0)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </main>
  );
}
