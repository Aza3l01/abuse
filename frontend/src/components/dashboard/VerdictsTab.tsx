"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Verdict {
  id: string;
  timestamp: string;
  ip: string;
  method: string | null;
  endpoint: string | null;
  threat_type: string | null;
  severity: string;
  confidence: number;
  agents_triggered: string[] | null;
  explanation: string | null;
  blocked: boolean;
  cost_prevented: number | null;
}

interface VerdictList {
  items: Verdict[];
  total: number;
  page: number;
  limit: number;
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

const SEVERITIES = ["critical", "high", "medium", "low"] as const;

// Item 18: human-readable attack type labels. Internal ThreatType enum
// values should never reach the UI verbatim.
const THREAT_LABELS: Record<string, string> = {
  DOS: "DoS Flood",
  DDOS: "DDoS",
  BRUTE_FORCE: "Brute Force",
  CREDENTIAL_STUFFING: "Credential Stuffing",
  BOT_ACTIVITY: "Bot Activity",
  SCRAPING: "Scraping",
  PORT_SCAN: "Port Scan",
  ENUMERATION: "Enumeration",
  SEQUENCE_ABUSE: "Sequence Abuse",
  WEB_ATTACK: "Web Attack",
  GEO_ANOMALY: "Geo Anomaly",
  UNKNOWN_ABUSE: "Unknown Abuse",
  manual: "Manual Block",
};

function threatLabel(t: string | null): string {
  if (!t) return "—";
  return THREAT_LABELS[t] ?? t;
}

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

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function absTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

const DATE_PRESETS = [
  { label: "24h", days: 1 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
] as const;

const PAGE_SIZES = [10, 25, 50] as const;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function VerdictsTab() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const ipParam = searchParams.get("ip") ?? "";

  const [page,       setPage]       = useState(1);
  const [limit,      setLimit]      = useState<number>(25);
  const [severities, setSeverities] = useState<string[]>([]);
  const [ip,         setIp]         = useState(ipParam);
  const [threatType, setThreatType] = useState("");
  const [threatTypes, setThreatTypes] = useState<string[]>([]);
  const [datePreset, setDatePreset] = useState<number | "custom">(30);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo,   setCustomTo]   = useState("");
  const [data,       setData]       = useState<VerdictList | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [blocking,   setBlocking]   = useState<string | null>(null);
  const [copiedIp,   setCopiedIp]   = useState<string | null>(null);

  useEffect(() => {
    apiFetch(`/verdicts/threat-types`)
      .then(r => r.ok ? r.json() : [])
      .then((rows: string[]) => setThreatTypes(rows))
      .catch(() => {/* dropdown just stays empty */});
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);

    const qs = new URLSearchParams({ page: String(page), limit: String(limit) });
    severities.forEach(s => qs.append("severity", s));
    if (ip) qs.set("ip", ip);
    if (threatType) qs.set("threat_type", threatType);

    if (datePreset === "custom") {
      if (customFrom) qs.set("date_from", new Date(customFrom).toISOString());
      if (customTo) qs.set("date_to", new Date(customTo).toISOString());
    } else {
      const from = new Date(Date.now() - datePreset * 86400000);
      qs.set("date_from", from.toISOString());
    }

    apiFetch(`/verdicts?${qs}`)
      .then(r => {
        if (!r.ok) throw new Error("API error");
        return r.json();
      })
      .then(d => { if (d) setData(d); })
      .catch(() => setError("Failed to load alerts."))
      .finally(() => setLoading(false));
  }, [page, limit, severities, ip, threatType, datePreset, customFrom, customTo]);

  useEffect(() => { load(); }, [load]);

  function toggleSeverity(sev: string) {
    setSeverities(prev => prev.includes(sev) ? prev.filter(s => s !== sev) : [...prev, sev]);
    setPage(1);
  }

  function applyIpFilter(newIp: string) {
    setIp(newIp);
    setPage(1);
  }

  function copyIp(value: string) {
    navigator.clipboard?.writeText(value).catch(() => {});
    setCopiedIp(value);
    setTimeout(() => setCopiedIp(null), 1200);
  }

  async function handleBlock(verdictId: string, currentlyBlocked: boolean) {
    setBlocking(verdictId);
    const action = currentlyBlocked ? "unblock" : "block";
    try {
      const r = await apiFetch(`/verdicts/${verdictId}/${action}`, { method: "POST" });
      if (r.status === 403) { alert("Blocking requires Growth or Pro plan."); return; }
      if (r.ok) load();
    } finally {
      setBlocking(null);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / limit)) : 1;
  const pageNumbers = Array.from({ length: totalPages }, (_, i) => i + 1).slice(
    Math.max(0, page - 3), Math.max(0, page - 3) + 5
  );

  return (
    <div>
      {/* Filters */}
      <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginBottom: "20px" }}>
        <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", alignItems: "center" }}>
          {/* Severity multi-select */}
          <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            {SEVERITIES.map(sev => (
              <label key={sev} style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "12px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={severities.includes(sev)}
                  onChange={() => toggleSeverity(sev)}
                />
                <span style={{ textTransform: "capitalize" }}>{sev}</span>
              </label>
            ))}
          </div>

          {/* Threat type */}
          <select
            value={threatType}
            onChange={e => { setThreatType(e.target.value); setPage(1); }}
            style={{ padding: "6px 10px", fontSize: "12px", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)", cursor: "pointer" }}
          >
            <option value="">All attack types</option>
            {threatTypes.map(t => (
              <option key={t} value={t}>{threatLabel(t)}</option>
            ))}
          </select>

          {/* IP */}
          <div style={{ display: "flex", gap: "4px" }}>
            <input
              type="text"
              placeholder="Filter by IP (e.g. 192.168.)"
              value={ip}
              onChange={e => setIp(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") applyIpFilter(ip); }}
              style={{ padding: "6px 10px", fontSize: "12px", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)", width: "170px" }}
            />
            {ip && (
              <button
                onClick={() => applyIpFilter("")}
                style={{ padding: "6px 10px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text-muted)", cursor: "pointer" }}
              >
                ×
              </button>
            )}
          </div>

          {/* Page size */}
          <select
            value={limit}
            onChange={e => { setLimit(Number(e.target.value)); setPage(1); }}
            style={{ padding: "6px 10px", fontSize: "12px", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)", cursor: "pointer", marginLeft: "auto" }}
          >
            {PAGE_SIZES.map(n => <option key={n} value={n}>{n} / page</option>)}
          </select>
        </div>

        {/* Date range presets */}
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          {DATE_PRESETS.map(p => (
            <button
              key={p.days}
              onClick={() => { setDatePreset(p.days); setPage(1); }}
              style={{
                padding: "4px 12px", fontSize: "12px",
                border: "1px solid var(--color-border)",
                background: datePreset === p.days ? "var(--color-text)" : "transparent",
                color: datePreset === p.days ? "var(--color-bg)" : "var(--color-text-muted)",
                cursor: "pointer",
              }}
            >
              {p.label}
            </button>
          ))}
          <button
            onClick={() => { setDatePreset("custom"); setPage(1); }}
            style={{
              padding: "4px 12px", fontSize: "12px",
              border: "1px solid var(--color-border)",
              background: datePreset === "custom" ? "var(--color-text)" : "transparent",
              color: datePreset === "custom" ? "var(--color-bg)" : "var(--color-text-muted)",
              cursor: "pointer",
            }}
          >
            Custom
          </button>
          {datePreset === "custom" && (
            <>
              <input type="date" value={customFrom} onChange={e => { setCustomFrom(e.target.value); setPage(1); }}
                style={{ padding: "5px 8px", fontSize: "12px", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)" }} />
              <span style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>to</span>
              <input type="date" value={customTo} onChange={e => { setCustomTo(e.target.value); setPage(1); }}
                style={{ padding: "5px 8px", fontSize: "12px", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)" }} />
            </>
          )}
          {data && (
            <span style={{ fontSize: "12px", color: "var(--color-text-muted)", marginLeft: "auto" }}>
              {data.total.toLocaleString()} result{data.total !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </div>

      {/* Table */}
      <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)" }}>
        {loading ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>Loading…</p>
        ) : error ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>{error}</p>
        ) : !data || data.items.length === 0 ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>
            No threats match the current filters.
          </p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr>
                {["Time", "IP", "Attack Type", "Severity", "Confidence", "Blocked", "Actions"].map(h => (
                  <th key={h} style={{
                    padding: "10px 16px", textAlign: "left", fontSize: "11px",
                    textTransform: "uppercase", letterSpacing: "0.06em",
                    color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", fontWeight: 500,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map(v => (
                <tr key={v.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                  <td title={absTime(v.timestamp)} style={{ padding: "10px 16px", color: "var(--color-text-muted)", whiteSpace: "nowrap", fontSize: "12px", cursor: "help" }}>
                    {relativeTime(v.timestamp)}
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    <span
                      onClick={() => copyIp(v.ip)}
                      title="Click to copy"
                      style={{ fontFamily: "var(--font-mono)", fontSize: "12px", cursor: "pointer" }}
                    >
                      {copiedIp === v.ip ? "Copied!" : v.ip}
                    </span>
                  </td>
                  <td style={{ padding: "10px 16px", color: "var(--color-text-muted)" }}>
                    {threatLabel(v.threat_type)}
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    <SeverityBadge severity={v.severity} />
                  </td>
                  <td style={{ padding: "10px 16px", fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--color-text-muted)" }}>
                    {(v.confidence * 100).toFixed(0)}%
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    {v.blocked ? (
                      <span style={{
                        padding: "2px 6px", fontSize: "10px", fontWeight: 600,
                        letterSpacing: "0.06em", textTransform: "uppercase",
                        color: "#fff", background: "var(--color-low)",
                      }}>
                        Blocked
                      </span>
                    ) : "—"}
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <button
                        onClick={() => router.push(`/dashboard/verdicts/${v.id}`)}
                        style={{ padding: "2px 10px", fontSize: "11px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
                      >
                        View
                      </button>
                      <button
                        onClick={() => handleBlock(v.id, v.blocked)}
                        disabled={blocking === v.id}
                        style={{
                          padding: "2px 8px", fontSize: "10px", border: "1px solid var(--color-border)",
                          background: "transparent", color: "var(--color-text-muted)",
                          cursor: blocking === v.id ? "default" : "pointer",
                          opacity: blocking === v.id ? 0.5 : 1, whiteSpace: "nowrap",
                        }}
                      >
                        {blocking === v.id ? "…" : v.blocked ? "Unblock" : "Block"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: "6px", marginTop: "16px" }}>
          <button
            disabled={page <= 1}
            onClick={() => setPage(p => p - 1)}
            style={{ padding: "6px 12px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: page <= 1 ? "var(--color-text-muted)" : "var(--color-text)", cursor: page <= 1 ? "default" : "pointer" }}
          >
            ← Prev
          </button>
          {pageNumbers.map(n => (
            <button
              key={n}
              onClick={() => setPage(n)}
              style={{
                padding: "6px 12px", fontSize: "12px", border: "1px solid var(--color-border)",
                background: n === page ? "var(--color-text)" : "transparent",
                color: n === page ? "var(--color-bg)" : "var(--color-text)", cursor: "pointer",
              }}
            >
              {n}
            </button>
          ))}
          {pageNumbers[pageNumbers.length - 1] < totalPages && <span style={{ color: "var(--color-text-muted)", fontSize: "12px" }}>…</span>}
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(p => p + 1)}
            style={{ padding: "6px 12px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: page >= totalPages ? "var(--color-text-muted)" : "var(--color-text)", cursor: page >= totalPages ? "default" : "pointer" }}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
