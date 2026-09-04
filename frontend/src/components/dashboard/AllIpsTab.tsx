"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface IpRow {
  id: string;
  ip: string;
  first_seen: string;
  last_seen: string;
  total_requests: number;
  threat_count: number;
  risk_score: number;
  highest_severity: string | null;
  geo_country: string | null;
  geo_asn_number: number | null;
  geo_asn_org: string | null;
  waf_blocked: boolean;
  cloudflare_blocked: boolean;
}

interface IpList {
  items: IpRow[];
  total: number;
  page: number;
  limit: number;
}

type SortKey = "risk_score" | "threat_count" | "last_seen" | "total_requests";

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
      display: "inline-block", padding: "2px 6px", fontSize: "10px", fontWeight: 600,
      letterSpacing: "0.06em", textTransform: "uppercase", color: "#fff",
      background: SEV_COLOR[severity] ?? "#888",
    }}>
      {severity}
    </span>
  );
}

function flagEmoji(code: string | null): string {
  if (!code || code.length !== 2) return "";
  const base = 0x1F1E6;
  const chars = [...code.toUpperCase()].map(c => base + (c.charCodeAt(0) - 65));
  return String.fromCodePoint(...chars);
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric",
  });
}

const LIMIT = 25;

function SortArrow({ active, order }: { active: boolean; order: "asc" | "desc" }) {
  if (!active) return null;
  return (
    <span style={{ marginLeft: "4px", fontSize: "9px" }}>
      {order === "desc" ? "▼" : "▲"}
    </span>
  );
}

function ColHeader({ col, label, sort, order, onToggle }: {
  col: SortKey; label: string; sort: SortKey; order: "asc" | "desc"; onToggle: (col: SortKey) => void;
}) {
  return (
    <th
      onClick={() => onToggle(col)}
      style={{
        padding: "10px 16px", textAlign: "left", fontSize: "11px",
        textTransform: "uppercase", letterSpacing: "0.06em",
        color: sort === col ? "var(--color-text)" : "var(--color-text-muted)",
        borderBottom: "1px solid var(--color-border)", fontWeight: 500,
        cursor: "pointer", userSelect: "none", whiteSpace: "nowrap",
      }}
    >
      {label}
      <SortArrow active={sort === col} order={order} />
    </th>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AllIpsTab() {
  const [page,    setPage]    = useState(1);
  const [sort,    setSort]    = useState<SortKey>("risk_score");
  const [order,   setOrder]   = useState<"asc" | "desc">("desc");
  const [country, setCountry] = useState("");
  const [data,    setData]    = useState<IpList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);

    const qs = new URLSearchParams({ page: String(page), limit: String(LIMIT), sort, order });
    if (country) qs.set("country", country);

    apiFetch(`/ips?${qs}`)
      .then(r => {
        if (!r.ok) throw new Error("API error");
        return r.json();
      })
      .then(d => { if (d) setData(d); })
      .catch(() => setError("Failed to load IP data."))
      .finally(() => setLoading(false));
  }, [page, sort, order, country]);

  useEffect(() => { load(); }, [load]);

  function toggleSort(col: SortKey) {
    if (sort === col) {
      setOrder(o => o === "desc" ? "asc" : "desc");
    } else {
      setSort(col);
      setOrder("desc");
    }
    setPage(1);
  }

  const totalPages = data ? Math.ceil(data.total / LIMIT) : 0;

  return (
    <div>
      {/* Country filter */}
      <div style={{ display: "flex", gap: "8px", marginBottom: "20px", alignItems: "center" }}>
        <div style={{ display: "flex", gap: "4px" }}>
          <input
            type="text"
            placeholder="Country code (e.g. US)"
            value={country}
            onChange={e => { setCountry(e.target.value.toUpperCase().slice(0, 2)); setPage(1); }}
            maxLength={2}
            style={{ padding: "6px 10px", fontSize: "12px", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)", width: "200px", textTransform: "uppercase" }}
          />
          {country && (
            <button
              onClick={() => { setCountry(""); setPage(1); }}
              style={{ padding: "6px 10px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text-muted)", cursor: "pointer" }}
            >
              ×
            </button>
          )}
        </div>

        {data && (
          <span style={{ fontSize: "12px", color: "var(--color-text-muted)", marginLeft: "auto" }}>
            {data.total.toLocaleString()} IP{data.total !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Table */}
      <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)" }}>
        {loading ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>Loading…</p>
        ) : error ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>{error}</p>
        ) : !data || data.items.length === 0 ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>
            No IPs tracked yet. They appear here once your logs are processed.
          </p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr>
                <th style={{ padding: "10px 16px", textAlign: "left", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", fontWeight: 500 }}>IP</th>
                <th style={{ padding: "10px 16px", textAlign: "left", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", fontWeight: 500 }}>Country</th>
                <th style={{ padding: "10px 16px", textAlign: "left", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", fontWeight: 500 }}>ASN</th>
                <th style={{ padding: "10px 16px", textAlign: "left", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", fontWeight: 500 }}>Highest Severity</th>
                <ColHeader col="risk_score"     label="Risk Score" sort={sort} order={order} onToggle={toggleSort} />
                <ColHeader col="threat_count"   label="Threats" sort={sort} order={order} onToggle={toggleSort} />
                <ColHeader col="total_requests" label="Requests" sort={sort} order={order} onToggle={toggleSort} />
                <ColHeader col="last_seen"      label="Last Seen" sort={sort} order={order} onToggle={toggleSort} />
                <th style={{ padding: "10px 16px", textAlign: "left", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", fontWeight: 500 }}>Blocked</th>
                <th style={{ padding: "10px 16px", textAlign: "left", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", fontWeight: 500 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map(row => (
                <tr key={row.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                  <td style={{ padding: "10px 16px" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px" }}>{row.ip}</span>
                  </td>
                  <td style={{ padding: "10px 16px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", fontSize: "12px" }}>
                    {flagEmoji(row.geo_country)} {row.geo_country ?? "—"}
                  </td>
                  <td style={{ padding: "10px 16px", color: "var(--color-text-muted)", fontSize: "12px" }}>
                    {row.geo_asn_org ?? "—"}
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    {row.highest_severity ? <SeverityBadge severity={row.highest_severity} /> : "—"}
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{
                        fontFamily: "var(--font-mono)", fontSize: "12px",
                        fontWeight: row.risk_score >= 0.6 ? 600 : 400,
                        color: row.risk_score >= 0.8 ? SEV_COLOR.critical : row.risk_score >= 0.6 ? SEV_COLOR.high : row.risk_score >= 0.4 ? SEV_COLOR.medium : SEV_COLOR.low,
                      }}>
                        {(row.risk_score * 100).toFixed(0)}%
                      </span>
                      <div style={{ width: "48px", height: "2px", background: "var(--color-border)" }}>
                        <div style={{
                          height: "100%", width: `${(row.risk_score * 100).toFixed(0)}%`,
                          background: row.risk_score >= 0.8 ? SEV_COLOR.critical : row.risk_score >= 0.6 ? SEV_COLOR.high : row.risk_score >= 0.4 ? SEV_COLOR.medium : SEV_COLOR.low,
                        }} />
                      </div>
                    </div>
                  </td>
                  <td style={{ padding: "10px 16px", fontFamily: "var(--font-mono)", fontSize: "12px" }}>
                    {row.threat_count.toLocaleString()}
                  </td>
                  <td style={{ padding: "10px 16px", fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--color-text-muted)" }}>
                    {row.total_requests.toLocaleString()}
                  </td>
                  <td style={{ padding: "10px 16px", fontSize: "12px", color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>
                    {fmtDate(row.last_seen)}
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    {(row.waf_blocked || row.cloudflare_blocked) ? (
                      <span style={{ padding: "2px 6px", fontSize: "10px", fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: "#fff", background: "var(--color-low)" }}>
                        Blocked
                      </span>
                    ) : "—"}
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    <Link
                      href={`/dashboard/alerts?ip=${row.ip}`}
                      style={{ fontSize: "11px", color: "var(--color-text-muted)", textDecoration: "none", whiteSpace: "nowrap" }}
                    >
                      View verdicts →
                    </Link>
                  </td>
                </tr>
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
            style={{ padding: "6px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: page <= 1 ? "var(--color-text-muted)" : "var(--color-text)", cursor: page <= 1 ? "default" : "pointer" }}
          >
            ← Prev
          </button>
          <span style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
            Page {page} of {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(p => p + 1)}
            style={{ padding: "6px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: page >= totalPages ? "var(--color-text-muted)" : "var(--color-text)", cursor: page >= totalPages ? "default" : "pointer" }}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
