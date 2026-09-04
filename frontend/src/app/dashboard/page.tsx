"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import Link from "next/link";

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
  highest_severity: string | null;
  geo_country: string | null;
  geo_asn_org: string | null;
  blocked: boolean;
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
  s3_configured: boolean;
  s3_connected_at: string | null;
  s3_status: string | null;
  s3_status_message: string | null;
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

// CSS flexbox stacked bar chart (no SVG scaling): bars/labels stay a fixed
// small pixel size; with few days the columns grow to fill the available
// width, with many days they shrink to a floor width and the row scrolls
// horizontally instead of clipping.
function TrendChart({ trend }: { trend: TrendDay[] }) {
  if (!trend.length) return null;

  const H = 64;
  const SEV_ORDER = ["low", "medium", "high", "critical"] as const;
  const COLORS = { critical: "#E53E3E", high: "#DD6B20", medium: "#D69E2E", low: "#38A169" };
  const maxTotal = Math.max(1, ...trend.map(d =>
    SEV_ORDER.reduce((s, k) => s + (d[k] || 0), 0)
  ));
  // Bars always render for every day; date labels are thinned to a max of
  // ~8 visible so a 30/90-day window stays readable instead of packing a
  // label under every single bar. Hidden labels keep their layout space
  // (visibility, not display) so column widths/alignment stay identical.
  const labelStep = Math.max(1, Math.ceil(trend.length / 8));

  return (
    <div style={{ overflowX: "auto" }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: "4px" }}>
        {trend.map((day, i) => (
          <div
            key={day.date}
            style={{ flex: "1 1 0%", minWidth: "22px", display: "flex", flexDirection: "column", alignItems: "center", gap: "6px" }}
          >
            <div style={{ width: "10px", height: `${H}px`, display: "flex", flexDirection: "column-reverse" }}>
              {SEV_ORDER.map(sev => {
                const count = day[sev] || 0;
                if (!count) return null;
                const barH = Math.max(1, (count / maxTotal) * H);
                return <div key={sev} style={{ width: "100%", height: `${barH}px`, background: COLORS[sev] }} />;
              })}
            </div>
            <span
              style={{
                fontSize: "10px",
                color: "var(--color-text-muted)",
                whiteSpace: "nowrap",
                visibility: i % labelStep === 0 ? "visible" : "hidden",
              }}
            >
              {day.date.slice(5)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// ISO 3166-1 alpha-2 → flag emoji (regional indicator symbols)
function flagEmoji(code: string | null): string {
  if (!code || code.length !== 2) return "";
  const base = 0x1F1E6;
  const chars = [...code.toUpperCase()].map(c => base + (c.charCodeAt(0) - 65));
  return String.fromCodePoint(...chars);
}

function NotConfiguredBox() {
  return (
    <div style={{
      border: "1px dashed var(--color-border)",
      padding: "48px 24px",
      textAlign: "center",
      marginBottom: "28px",
    }}>
      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "16px" }}>
        Connect your S3 bucket to start monitoring
      </p>
      <Link href="/dashboard/settings#s3" style={{
        display: "inline-block",
        padding: "8px 20px",
        fontSize: "13px",
        border: "1px solid var(--color-text)",
        background: "var(--color-text)",
        color: "var(--color-bg)",
        textDecoration: "none",
      }}>
        Connect S3 → Settings
      </Link>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardOverview() {
  const [days,     setDays]     = useState(7);
  const [summary,  setSummary]  = useState<Summary | null>(null);
  const [recent,   setRecent]   = useState<Verdict[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const load = () => {
    return Promise.all([
      apiFetch(`/dashboard/summary?days=${days}`),
      apiFetch(`/verdicts?limit=10`),
    ])
      .then(async ([sr, vr]) => {
        if (!sr.ok || !vr.ok) throw new Error("API error");
        const [s, v] = await Promise.all([sr.json(), vr.json()]);
        setSummary(s);
        setRecent(v.items ?? []);
        setLastChecked(new Date());
      })
      .catch(() => setError("Failed to load dashboard data."));
  };

  useEffect(() => {
    setLoading(true);
    setError(null);
    load().finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days]);

  // Item 15's auto-polling window: every 30s for the first 30 minutes after
  // s3_connected_at, only while there are still zero verdicts. Stops itself
  // once data arrives or the window elapses. Never polls indefinitely.
  useEffect(() => {
    if (!summary?.s3_configured || !summary.s3_connected_at) return;
    if (summary.total_threats > 0) return;
    const connectedAt = new Date(summary.s3_connected_at).getTime();
    if (Date.now() - connectedAt >= 30 * 60 * 1000) return;

    const id = setInterval(() => { load(); }, 30000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary?.s3_connected_at, summary?.total_threats, summary?.s3_configured]);

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
  const noDataYet = s.s3_configured && s.total_threats === 0;
  // lastChecked is always set by the time summary is (both come from the same
  // load() resolution) — use it as "now" instead of calling Date.now() in render.
  const now = lastChecked?.getTime() ?? 0;
  const withinScanWindow = !!s.s3_connected_at && now > 0 && (now - new Date(s.s3_connected_at).getTime()) < 30 * 60 * 1000;
  const scanning = noDataYet && withinScanWindow;

  return (
    <main style={{ padding: "32px", width: "100%" }}>

      {/* Item 15: persistent scanning banner. Dismissed automatically once
          the first verdict arrives (noDataYet flips false) or the 30-min
          window elapses (replaced by the manual refresh button below). */}
      {scanning && (
        <div style={{
          padding: "10px 16px",
          marginBottom: "20px",
          border: "1px solid var(--color-border)",
          background: "var(--color-surface)",
          fontSize: "12px",
          color: "var(--color-text-muted)",
        }}>
          Scanning in progress. Your first results will appear here within 15 minutes.
        </div>
      )}

      {/* Title + period selector */}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: "28px" }}>
        <h1 style={{ fontFamily: "var(--font-brand)", fontSize: "22px", fontWeight: 700 }}>
          Overview
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          {!scanning && s.s3_configured && lastChecked && (
            <>
              <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
                Checked {lastChecked.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
              </span>
              <button
                onClick={() => load()}
                style={{
                  padding: "4px 12px", fontSize: "12px",
                  border: "1px solid var(--color-border)",
                  background: "transparent", color: "var(--color-text)", cursor: "pointer",
                }}
              >
                Refresh
              </button>
            </>
          )}
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
      </div>

      {!s.s3_configured && <NotConfiguredBox />}

      {/* Stat cards */}
      <div style={{ display: "flex", gap: "12px", marginBottom: "28px" }}>
        <StatCard
          label="Total threats"
          value={s.s3_configured ? s.total_threats.toLocaleString() : "—"}
          sub={s.s3_configured ? (noDataYet ? "No data yet" : `+${s.new_threats_today} today`) : undefined}
        />
        <StatCard
          label="Critical"
          value={s.s3_configured ? s.by_severity.critical.toLocaleString() : "—"}
          sub={noDataYet ? "No data yet" : undefined}
        />
        <StatCard
          label="IPs flagged"
          value={s.s3_configured ? s.ips_flagged.toLocaleString() : "—"}
          sub={noDataYet ? "No data yet" : undefined}
        />
        <StatCard
          label="Cost prevented"
          value={s.s3_configured ? `$${s.cost_prevented.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—"}
          sub={noDataYet ? "No data yet" : undefined}
        />
      </div>

      {/* Trend chart + top IPs */}
      {s.s3_configured && (
      <div style={{ display: "flex", gap: "12px", marginBottom: "28px" }}>
        {/* Chart */}
        <div style={{
          flex: "2 1 0",
          border: "1px solid var(--color-border)",
          background: "var(--color-surface)",
          padding: "20px",
        }}>
          <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--color-text-muted)", marginBottom: "16px" }}>
            Threat trend, {days}d
          </p>
          {noDataYet ? (
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)", padding: "24px 0", textAlign: "center" }}>
              No threats detected yet. Your first scan runs within 15 minutes.
            </p>
          ) : s.trend.every(d => d.critical + d.high + d.medium + d.low === 0) ? (
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
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>No IPs flagged yet</p>
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
                      {flagEmoji(tip.geo_country)} {tip.geo_country ?? "—"} · {tip.geo_asn_org ?? "—"}
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "2px" }}>
                    <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
                      {tip.count} hits
                    </span>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      {tip.highest_severity && <SeverityBadge severity={tip.highest_severity} />}
                      {tip.blocked && (
                        <span style={{ fontSize: "10px", color: "var(--color-low)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Blocked</span>
                      )}
                    </div>
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
      )}

      {/* Recent verdicts */}
      {s.s3_configured && (
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
          <div style={{ padding: "32px 20px", textAlign: "center" }}>
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "12px" }}>
              No threats detected yet. Your first scan runs within 15 minutes of connecting S3.
            </p>
            <Link href="/dashboard/settings#s3" style={{ fontSize: "12px", color: "var(--color-text)", textDecoration: "none" }}>
              Check Settings →
            </Link>
          </div>
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
      )}
    </main>
  );
}
