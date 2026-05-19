"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { API_URL } from "@/lib/api";
import { Suspense } from "react";

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

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Inner component (uses useSearchParams — wrapped in Suspense below)
// ---------------------------------------------------------------------------

function AlertsInner() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  const ipParam      = searchParams.get("ip") ?? "";

  const LIMIT = 25;

  const [page,       setPage]       = useState(1);
  const [severity,   setSeverity]   = useState("");
  const [ip,         setIp]         = useState(ipParam);
  const [data,       setData]       = useState<VerdictList | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [blocking,   setBlocking]   = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);

    const qs = new URLSearchParams({ page: String(page), limit: String(LIMIT) });
    if (severity) qs.set("severity", severity);
    if (ip)       qs.set("ip", ip);

    fetch(`${API_URL}/verdicts?${qs}`, { credentials: "include" })
      .then(r => {
        if (r.status === 401) { router.push("/login"); return null; }
        if (!r.ok) throw new Error("API error");
        return r.json();
      })
      .then(d => { if (d) setData(d); })
      .catch(() => setError("Failed to load alerts."))
      .finally(() => setLoading(false));
  }, [page, severity, ip, router]);

  useEffect(() => { load(); }, [load]);

  // Reset to page 1 when filters change
  function applyFilter(newSev: string, newIp: string) {
    setSeverity(newSev);
    setIp(newIp);
    setPage(1);
  }

  async function handleBlock(verdictId: string, currentlyBlocked: boolean) {
    setBlocking(verdictId);
    const action = currentlyBlocked ? "unblock" : "block";
    try {
      const r = await fetch(`${API_URL}/verdicts/${verdictId}/${action}`, {
        method: "POST",
        credentials: "include",
      });
      if (r.status === 401) { router.push("/login"); return; }
      if (r.status === 403) { alert("Blocking requires Growth or Pro plan."); return; }
      if (r.ok) load();
    } finally {
      setBlocking(null);
    }
  }

  const totalPages = data ? Math.ceil(data.total / LIMIT) : 0;

  return (
    <main style={{ padding: "32px", width: "100%" }}>

      {/* Title */}
      <h1 style={{ fontFamily: "var(--font-brand)", fontSize: "22px", fontWeight: 700, marginBottom: "24px" }}>
        Alerts
      </h1>

      {/* Filters */}
      <div style={{
        display: "flex",
        gap: "8px",
        marginBottom: "20px",
        flexWrap: "wrap",
      }}>
        <select
          value={severity}
          onChange={e => applyFilter(e.target.value, ip)}
          style={{
            padding: "6px 10px",
            fontSize: "12px",
            border: "1px solid var(--color-border)",
            background: "var(--color-surface)",
            color: "var(--color-text)",
            cursor: "pointer",
          }}
        >
          <option value="">All severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>

        <div style={{ display: "flex", gap: "4px" }}>
          <input
            type="text"
            placeholder="Filter by IP"
            value={ip}
            onChange={e => setIp(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") applyFilter(severity, ip); }}
            style={{
              padding: "6px 10px",
              fontSize: "12px",
              border: "1px solid var(--color-border)",
              background: "var(--color-surface)",
              color: "var(--color-text)",
              width: "160px",
            }}
          />
          {ip && (
            <button
              onClick={() => applyFilter(severity, "")}
              style={{
                padding: "6px 10px",
                fontSize: "12px",
                border: "1px solid var(--color-border)",
                background: "transparent",
                color: "var(--color-text-muted)",
                cursor: "pointer",
              }}
            >
              ×
            </button>
          )}
        </div>

        {data && (
          <span style={{ fontSize: "12px", color: "var(--color-text-muted)", alignSelf: "center", marginLeft: "auto" }}>
            {data.total.toLocaleString()} result{data.total !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Table */}
      <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)" }}>
        {loading ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>
            Loading…
          </p>
        ) : error ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>
            {error}
          </p>
        ) : !data || data.items.length === 0 ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>
            No threats match the current filters.
          </p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr>
                {["Time", "IP", "Method", "Endpoint", "Threat", "Sev", "Conf", "Status"].map(h => (
                  <th key={h} style={{
                    padding: "10px 16px",
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
              {data.items.map(v => (
                <>
                  <tr
                    key={v.id}
                    onClick={() => setExpandedId(expandedId === v.id ? null : v.id)}
                    style={{
                      borderBottom: "1px solid var(--color-border)",
                      cursor: "pointer",
                      background: expandedId === v.id ? "var(--color-bg)" : "transparent",
                    }}
                  >
                    <td style={{ padding: "10px 16px", color: "var(--color-text-muted)", whiteSpace: "nowrap", fontSize: "12px" }}>
                      {fmtTime(v.timestamp)}
                    </td>
                    <td style={{ padding: "10px 16px" }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px" }}>{v.ip}</span>
                    </td>
                    <td style={{ padding: "10px 16px", fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--color-text-muted)" }}>
                      {v.method ?? "—"}
                    </td>
                    <td style={{ padding: "10px 16px", maxWidth: "220px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {v.endpoint ?? "—"}
                    </td>
                    <td style={{ padding: "10px 16px", color: "var(--color-text-muted)" }}>
                      {v.threat_type ?? "—"}
                    </td>
                    <td style={{ padding: "10px 16px" }}>
                      <SeverityBadge severity={v.severity} />
                    </td>
                    <td style={{ padding: "10px 16px", fontFamily: "var(--font-mono)", fontSize: "12px" }}>
                      {(v.confidence * 100).toFixed(0)}%
                    </td>
                    <td style={{ padding: "10px 16px" }} onClick={e => e.stopPropagation()}>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        {v.blocked && (
                          <span style={{
                            padding: "2px 6px",
                            fontSize: "10px",
                            fontWeight: 600,
                            letterSpacing: "0.06em",
                            textTransform: "uppercase",
                            border: "1px solid var(--color-critical)",
                            color: "var(--color-critical)",
                          }}>
                            blocked
                          </span>
                        )}
                        <button
                          onClick={() => handleBlock(v.id, v.blocked)}
                          disabled={blocking === v.id}
                          style={{
                            padding: "2px 8px",
                            fontSize: "10px",
                            border: "1px solid var(--color-border)",
                            background: "transparent",
                            color: "var(--color-text-muted)",
                            cursor: blocking === v.id ? "default" : "pointer",
                            opacity: blocking === v.id ? 0.5 : 1,
                            whiteSpace: "nowrap",
                          }}
                        >
                          {blocking === v.id ? "…" : v.blocked ? "Unblock" : "Block"}
                        </button>
                      </div>
                    </td>
                  </tr>

                  {/* Expanded detail row */}
                  {expandedId === v.id && (
                    <tr key={`${v.id}-detail`} style={{ borderBottom: "1px solid var(--color-border)", background: "var(--color-bg)" }}>
                      <td colSpan={8} style={{ padding: "16px 20px" }}>
                        {v.explanation && (
                          <p style={{ fontSize: "13px", marginBottom: "12px", lineHeight: "1.5" }}>
                            {v.explanation}
                          </p>
                        )}
                        {v.agents_triggered && v.agents_triggered.length > 0 && (
                          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                            <span style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", alignSelf: "center" }}>
                              Agents:
                            </span>
                            {v.agents_triggered.map(a => (
                              <span key={a} style={{
                                padding: "2px 8px",
                                fontSize: "11px",
                                border: "1px solid var(--color-border)",
                                color: "var(--color-text-muted)",
                              }}>
                                {a}
                              </span>
                            ))}
                          </div>
                        )}
                        {!v.explanation && (!v.agents_triggered || v.agents_triggered.length === 0) && (
                          <p style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>No detail available.</p>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "16px" }}>
          <button
            disabled={page <= 1}
            onClick={() => setPage(p => p - 1)}
            style={{
              padding: "6px 16px",
              fontSize: "12px",
              border: "1px solid var(--color-border)",
              background: "transparent",
              color: page <= 1 ? "var(--color-text-muted)" : "var(--color-text)",
              cursor: page <= 1 ? "default" : "pointer",
            }}
          >
            ← Prev
          </button>
          <span style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
            Page {page} of {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(p => p + 1)}
            style={{
              padding: "6px 16px",
              fontSize: "12px",
              border: "1px solid var(--color-border)",
              background: "transparent",
              color: page >= totalPages ? "var(--color-text-muted)" : "var(--color-text)",
              cursor: page >= totalPages ? "default" : "pointer",
            }}
          >
            Next →
          </button>
        </div>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Page — wrap in Suspense for useSearchParams()
// ---------------------------------------------------------------------------

export default function AlertsPage() {
  return (
    <Suspense fallback={
      <main style={{ padding: "32px", color: "var(--color-text-muted)", fontSize: "13px" }}>
        Loading…
      </main>
    }>
      <AlertsInner />
    </Suspense>
  );
}
