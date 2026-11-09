"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { apiFetch } from "@/lib/api";
import { SITE_URL } from "@/lib/urls";
import Link from "next/link";
import { GuidedOnboardingButton } from "@/components/dashboard/GuidedOnboardingButton";
import { LoadingCursor } from "@/components/dashboard/LoadingCursor";
import { TrendLines } from "@/components/dashboard/charts/TrendLines";
import { Donut } from "@/components/dashboard/charts/Donut";
import { RiskScatter } from "@/components/dashboard/charts/Scatter";
import { tierDisplayName } from "@/lib/pricing";

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
  tier: string;
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
  monthly_requests_processed: number;
  // null for tiers with no fixed call volume (enterprise).
  monthly_requests_cap: number | null;
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

function StatCard({ label, value, sub, note, noteHref }: { label: string; value: string; sub?: string; note?: string; noteHref?: string }) {
  return (
    <div style={{
      border: "1px solid var(--color-border)",
      background: "var(--color-surface)",
      padding: "20px",
      flex: "1 1 140px",
      minWidth: "140px",
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
      {note && (
        <p style={{ fontSize: "10px", color: "var(--color-text-muted)", marginTop: "6px" }}>
          {note}{" "}
          {noteHref && (
            <Link href={noteHref} style={{ color: "var(--color-text-muted)", textDecoration: "underline" }}>
              Learn more
            </Link>
          )}
        </p>
      )}
    </div>
  );
}

// Monthly call volume against the tier's cap. Scanning pauses at the cap
// (same rule as UsageBanner). Enterprise has no fixed cap.
function UsageBar({ used, cap }: { used: number; cap: number | null }) {
  const ratio = cap ? used / cap : 0;
  const color = ratio >= 1 ? "var(--color-critical)" : ratio >= 0.8 ? "var(--color-high)" : "var(--color-text)";
  return (
    <div style={{
      border: "1px solid var(--color-border)",
      background: "var(--color-surface)",
      padding: "20px",
      marginBottom: "28px",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "8px", marginBottom: "12px" }}>
        <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--color-text-muted)" }}>
          Monthly call volume
        </p>
        <p style={{ fontSize: "12px", fontFamily: "var(--font-mono)" }}>
          {used.toLocaleString("en-US")}
          {cap ? ` / ${cap.toLocaleString("en-US")}` : " calls, no fixed cap"}
          {cap ? <span style={{ color: "var(--color-text-muted)" }}>{` (${Math.floor(ratio * 100)}%)`}</span> : null}
        </p>
      </div>
      {cap ? (
        <>
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={cap}
            aria-valuenow={Math.min(used, cap)}
            aria-label="Monthly call volume used"
            style={{ height: "8px", border: "1px solid var(--color-border)", background: "var(--color-bg)" }}
          >
            <div style={{ height: "100%", width: `${Math.min(100, ratio * 100)}%`, background: color }} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "8px" }}>
            <p style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
              {ratio >= 1
                ? "Cap reached. Scanning is paused until your counter resets or you upgrade."
                : "Resets with your billing month. Scanning pauses at the cap."}
            </p>
            {ratio >= 0.8 && (
              <Link href="/settings#billing" style={{ fontSize: "11px", color, textDecoration: "underline" }}>
                Upgrade plan →
              </Link>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
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
      <Link href="/settings#s3" style={{
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
      <div style={{ marginTop: "16px" }}>
        <GuidedOnboardingButton />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function subscribeNever() {
  return () => {};
}

function readIsIndia() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const lang = navigator.language || "";
  return tz.includes("Kolkata") || tz.includes("Calcutta") || lang === "hi" || lang.endsWith("-IN");
}

export default function DashboardOverview() {
  const [days,     setDays]     = useState(7);
  const [lockedHint, setLockedHint] = useState(false);
  const [summary,  setSummary]  = useState<Summary | null>(null);
  const [recent,   setRecent]   = useState<Verdict[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  // Previously-seen recent-verdict ids, used to flash only genuinely new rows
  // on a reload (not on the very first page load).
  const seenVerdictIds = useRef<Set<string> | null>(null);
  const [flashIds, setFlashIds] = useState<Set<string>>(new Set());
  // Matches Settings' own locale/timezone heuristic for INR vs USD, so
  // "Cost prevented" doesn't show a flat USD figure to an org whose billing
  // (and everywhere else in the product) is already showing INR.
  const isIndia = useSyncExternalStore(subscribeNever, readIsIndia, () => false);

  const load = () => {
    return Promise.all([
      apiFetch(`/dashboard/summary?days=${days}`),
      apiFetch(`/verdicts?limit=10&sort=recent`),
    ])
      .then(async ([sr, vr]) => {
        if (!sr.ok || !vr.ok) throw new Error("API error");
        const [s, v] = await Promise.all([sr.json(), vr.json()]);
        setSummary(s);
        const items: Verdict[] = v.items ?? [];
        const ids = new Set(items.map(i => i.id));
        if (seenVerdictIds.current) {
          const newly = [...ids].filter(id => !seenVerdictIds.current!.has(id));
          if (newly.length > 0) {
            setFlashIds(new Set(newly));
            setTimeout(() => setFlashIds(new Set()), 1200);
          }
        }
        seenVerdictIds.current = ids;
        setRecent(items);
        setLastChecked(new Date());
      })
      .catch(() => setError("Failed to load dashboard data."));
  };

  useEffect(() => {
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
        Loading<LoadingCursor />
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
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: "28px", flexWrap: "wrap", gap: "12px" }}>
        <h1 style={{ fontFamily: "var(--font-brand)", fontSize: "22px", fontWeight: 700 }}>
          Overview
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
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
            {[7, 30].map(d => {
              // The free tier (Starter) keeps 7 days of history, so 30d is a Basic feature.
              const locked = d === 30 && s.tier === "free";
              return (
                <div
                  key={d}
                  style={{ position: "relative" }}
                  onMouseEnter={() => { if (locked) setLockedHint(true); }}
                  onMouseLeave={() => setLockedHint(false)}
                >
                  <button
                    aria-disabled={locked}
                    onClick={() => {
                      if (locked || d === days) return;
                      setLoading(true);
                      setError(null);
                      setDays(d);
                    }}
                    style={{
                      padding: "4px 12px",
                      fontSize: "12px",
                      border: "1px solid var(--color-border)",
                      background: days === d ? "var(--color-text)" : "transparent",
                      color:      days === d ? "var(--color-bg)"   : "var(--color-text-muted)",
                      cursor: locked ? "not-allowed" : "pointer",
                      opacity: locked ? 0.4 : 1,
                    }}
                  >
                    {d}d
                  </button>
                  {locked && lockedHint && (
                    <div style={{
                      position: "absolute", top: "100%", right: 0, marginTop: "4px", zIndex: 10,
                      padding: "4px 8px", fontSize: "11px", whiteSpace: "nowrap",
                      border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)",
                    }}>
                      Available in {tierDisplayName("starter")}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {!s.s3_configured && <NotConfiguredBox />}

      {/* Stat cards */}
      <div style={{ display: "flex", gap: "12px", marginBottom: "28px", flexWrap: "wrap" }}>
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
          note="Estimate only, confidence-weighted."
          noteHref={`${SITE_URL}/docs#cost-prevented-estimate`}
          value={s.s3_configured
            ? isIndia
              ? `₹${s.cost_prevented.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
              : `$${s.cost_prevented.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            : "—"}
          sub={noDataYet ? "No data yet" : undefined}
        />
      </div>

      {s.s3_configured && (
        <UsageBar used={s.monthly_requests_processed} cap={s.monthly_requests_cap} />
      )}

      {/* Trend chart + severity split */}
      {s.s3_configured && (
      <div style={{ display: "flex", gap: "12px", marginBottom: "12px", flexWrap: "wrap" }}>
        {/* Chart */}
        <div style={{
          flex: "2 1 320px",
          minWidth: "280px",
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
            <TrendLines trend={s.trend} />
          )}
        </div>

        {/* Severity split */}
        <div style={{
          flex: "1 1 260px",
          minWidth: "240px",
          border: "1px solid var(--color-border)",
          background: "var(--color-surface)",
          padding: "20px",
        }}>
          <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--color-text-muted)", marginBottom: "16px" }}>
            Severity split, {days}d
          </p>
          <Donut
            centerLabel="Threats"
            slices={(["critical", "high", "medium", "low"] as const).map(sev => ({
              key: sev,
              label: sev.charAt(0).toUpperCase() + sev.slice(1),
              value: s.by_severity[sev],
              color: SEV_COLOR[sev],
            }))}
          />
        </div>
      </div>
      )}

      {/* Top IPs: risk against hits, then the clickable list */}
      {s.s3_configured && (
      <div style={{ display: "flex", gap: "12px", marginBottom: "28px", flexWrap: "wrap" }}>
        <div style={{
          flex: "2 1 320px",
          minWidth: "280px",
          border: "1px solid var(--color-border)",
          background: "var(--color-surface)",
          padding: "20px",
        }}>
          <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--color-text-muted)", marginBottom: "16px" }}>
            Top threat IPs, risk vs hits
          </p>
          {s.top_ips.length === 0 ? (
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)", padding: "24px 0", textAlign: "center" }}>No IPs flagged yet</p>
          ) : (
            <RiskScatter
              xLabel="Hits"
              points={s.top_ips.map(tip => ({
                id: tip.ip,
                label: tip.ip,
                x: tip.count,
                y: tip.risk_score,
                severity: tip.highest_severity,
              }))}
            />
          )}
        </div>

        <div style={{
          flex: "1 1 260px",
          minWidth: "240px",
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
                  href={`/alerts?ip=${tip.ip}`}
                  style={{ textDecoration: "none", color: "inherit" }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px" }}>{tip.ip}</span>
                    <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
                      {tip.geo_country ?? "—"} · {tip.geo_asn_org ?? "—"}
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "2px" }}>
                    <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
                      {tip.count} hit{tip.count !== 1 ? "s" : ""} · risk {(tip.risk_score * 100).toFixed(0)}%
                    </span>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      {tip.highest_severity && <SeverityBadge severity={tip.highest_severity} />}
                      {tip.blocked && (
                        <span style={{ fontSize: "10px", color: "var(--color-low)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Blocked</span>
                      )}
                    </div>
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
        overflowX: "auto",
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
          <Link href="/alerts" style={{ fontSize: "12px", color: "var(--color-text-muted)", textDecoration: "none" }}>
            View all →
          </Link>
        </div>
        {recent.length === 0 ? (
          <div style={{ padding: "32px 20px", textAlign: "center" }}>
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "12px" }}>
              No threats detected yet. Your first scan runs within 15 minutes of connecting S3.
            </p>
            <Link href="/settings#s3" style={{ fontSize: "12px", color: "var(--color-text)", textDecoration: "none" }}>
              Check Settings →
            </Link>
          </div>
        ) : (
          <table style={{ width: "100%", minWidth: "760px", borderCollapse: "collapse", fontSize: "13px" }}>
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
                <tr
                  key={v.id}
                  style={{
                    borderBottom: "1px solid var(--color-border)",
                    animation: flashIds.has(v.id) ? "new-row-flash 1.2s ease-out" : undefined,
                  }}
                >
                  <td style={{ padding: "10px 20px", color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>
                    {fmtTime(v.timestamp)}
                  </td>
                  <td style={{ padding: "10px 20px" }}>
                    <Link href={`/alerts?ip=${v.ip}`} style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: "inherit", textDecoration: "none" }}>
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
