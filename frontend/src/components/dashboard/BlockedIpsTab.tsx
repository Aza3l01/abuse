"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";

interface BlockedIpRow {
  id: string;
  ip: string;
  last_seen: string;
  threat_count: number;
  waf_blocked: boolean;
  cloudflare_blocked: boolean;
  waf_block_error: string | null;
  cloudflare_block_error: string | null;
}

interface IpList {
  items: BlockedIpRow[];
  total: number;
  page: number;
  limit: number;
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function IntegrationBadge({ label, blocked, error }: { label: string; blocked: boolean; error: string | null }) {
  return (
    <span
      title={!blocked && error ? error : undefined}
      style={{
        display: "inline-flex", alignItems: "center", gap: "3px",
        padding: "2px 6px", fontSize: "10px", fontWeight: 600,
        border: `1px solid ${blocked ? "var(--color-low)" : "var(--color-critical)"}`,
        color: blocked ? "var(--color-low)" : "var(--color-critical)",
        cursor: !blocked && error ? "help" : "default",
      }}
    >
      {label} {blocked ? "✓" : "✗"}
    </span>
  );
}

// Item 21: Blocked IPs tab. Owner/admin get unblock + manual-block controls;
// other roles see the same table read-only.
export function BlockedIpsTab({ role }: { role: string | null }) {
  const [data, setData] = useState<IpList | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [confirmIp, setConfirmIp] = useState<BlockedIpRow | null>(null);
  const [unblocking, setUnblocking] = useState(false);

  const [showManualForm, setShowManualForm] = useState(false);
  const [manualIp, setManualIp] = useState("");
  const [manualReason, setManualReason] = useState("");
  const [manualSubmitting, setManualSubmitting] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);

  const LIMIT = 25;
  const canManage = role === "owner" || role === "admin";

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/ips?blocked_only=true&page=${page}&limit=${LIMIT}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setData(d); })
      .finally(() => setLoading(false));
  }, [page]);

  useEffect(() => { load(); }, [load]);

  async function handleUnblock() {
    if (!confirmIp) return;
    setUnblocking(true);
    try {
      const r = await apiFetch(`/ips/${confirmIp.ip}/unblock`, { method: "POST" });
      if (r.ok) {
        setConfirmIp(null);
        load();
      }
    } finally {
      setUnblocking(false);
    }
  }

  async function handleManualBlock(e: React.FormEvent) {
    e.preventDefault();
    setManualSubmitting(true);
    setManualError(null);
    try {
      const r = await apiFetch(`/verdicts/manual-block`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ip: manualIp, reason: manualReason || undefined }),
      });
      if (r.status === 403) { setManualError("Blocking requires Growth or Pro plan."); return; }
      if (!r.ok) { const d = await r.json().catch(() => ({})); setManualError(d?.detail ?? "Failed to block IP."); return; }
      setManualIp("");
      setManualReason("");
      setShowManualForm(false);
      load();
    } catch {
      setManualError("Network error. Please try again.");
    } finally {
      setManualSubmitting(false);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / LIMIT)) : 1;

  return (
    <div>
      {canManage && (
        <div style={{ marginBottom: "20px" }}>
          <button
            onClick={() => setShowManualForm(v => !v)}
            style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
          >
            {showManualForm ? "Cancel" : "Block an IP manually"}
          </button>

          {showManualForm && (
            <form onSubmit={handleManualBlock} style={{
              marginTop: "12px", padding: "16px", border: "1px solid var(--color-border)",
              background: "var(--color-surface)", display: "flex", flexDirection: "column", gap: "10px", maxWidth: "480px",
            }}>
              <input
                type="text"
                placeholder="IP address"
                value={manualIp}
                onChange={e => setManualIp(e.target.value)}
                required
                style={{ padding: "7px 10px", fontSize: "13px", border: "1px solid var(--color-border)", background: "var(--color-bg)", color: "var(--color-text)" }}
              />
              <input
                type="text"
                placeholder="Reason (optional)"
                value={manualReason}
                onChange={e => setManualReason(e.target.value)}
                style={{ padding: "7px 10px", fontSize: "13px", border: "1px solid var(--color-border)", background: "var(--color-bg)", color: "var(--color-text)" }}
              />
              {manualError && <p style={{ fontSize: "12px", color: "var(--color-critical)", margin: 0 }}>{manualError}</p>}
              <div>
                <button
                  type="submit"
                  disabled={manualSubmitting}
                  style={{
                    padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-text)",
                    background: "var(--color-text)", color: "var(--color-bg)",
                    cursor: manualSubmitting ? "default" : "pointer", opacity: manualSubmitting ? 0.6 : 1,
                  }}
                >
                  {manualSubmitting ? "Blocking…" : "Block IP"}
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)" }}>
        {loading ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>Loading…</p>
        ) : !data || data.items.length === 0 ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>
            No IPs are currently blocked.
          </p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr>
                {["IP", "Threats", "Last Seen", "WAF", "Cloudflare", ""].map(h => (
                  <th key={h} style={{
                    padding: "10px 16px", textAlign: "left", fontSize: "11px", textTransform: "uppercase",
                    letterSpacing: "0.06em", color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", fontWeight: 500,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map(row => (
                <tr key={row.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                  <td style={{ padding: "10px 16px", fontFamily: "var(--font-mono)", fontSize: "12px" }}>{row.ip}</td>
                  <td style={{ padding: "10px 16px", fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--color-text-muted)" }}>{row.threat_count}</td>
                  <td style={{ padding: "10px 16px", fontSize: "12px", color: "var(--color-text-muted)" }}>{fmtDate(row.last_seen)}</td>
                  <td style={{ padding: "10px 16px" }}>
                    <IntegrationBadge label="WAF" blocked={row.waf_blocked} error={row.waf_block_error} />
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    <IntegrationBadge label="CF" blocked={row.cloudflare_blocked} error={row.cloudflare_block_error} />
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    {canManage && (
                      <button
                        onClick={() => setConfirmIp(row)}
                        style={{ padding: "4px 10px", fontSize: "11px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
                      >
                        Unblock
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "16px" }}>
          <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
            style={{ padding: "6px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: page <= 1 ? "var(--color-text-muted)" : "var(--color-text)", cursor: page <= 1 ? "default" : "pointer" }}>
            ← Prev
          </button>
          <span style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>Page {page} of {totalPages}</span>
          <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}
            style={{ padding: "6px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: page >= totalPages ? "var(--color-text-muted)" : "var(--color-text)", cursor: page >= totalPages ? "default" : "pointer" }}>
            Next →
          </button>
        </div>
      )}

      {/* Unblock confirmation modal */}
      {confirmIp && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(13,13,13,0.6)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
        }}>
          <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", padding: "24px", maxWidth: "420px", width: "90%" }}>
            <p style={{ fontSize: "14px", marginBottom: "16px", lineHeight: 1.5 }}>
              Unblock <span style={{ fontFamily: "var(--font-mono)" }}>{confirmIp.ip}</span>?
            </p>
            <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "20px", lineHeight: 1.5 }}>
              This IP will be removed from your WAF and Cloudflare rules immediately. This action is logged.
            </p>
            <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
              <button
                onClick={() => setConfirmIp(null)}
                style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={handleUnblock}
                disabled={unblocking}
                style={{
                  padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-text)",
                  background: "var(--color-text)", color: "var(--color-bg)",
                  cursor: unblocking ? "default" : "pointer", opacity: unblocking ? 0.6 : 1,
                }}
              >
                {unblocking ? "Working…" : "Confirm Unblock"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
