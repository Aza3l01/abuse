"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

interface AlertSentRow {
  id: string;
  verdict_id: string;
  channel: string;
  sent_at: string;
  status: string;
  delivery_error: string | null;
  verdict_ip: string | null;
  verdict_severity: string | null;
  verdict_threat_type: string | null;
}

interface AlertSentList {
  items: AlertSentRow[];
  total: number;
  page: number;
  limit: number;
}

const STATUS_COLOR: Record<string, string> = {
  sent: "var(--color-low)",
  failed: "var(--color-critical)",
  bounced: "var(--color-high)",
};

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// Item 20: role prop controls whether the "Send test alert" button and
// alert-config context line are shown. Viewer-only sessions still see the
// delivery log (read-only), matching the rest of the dashboard's RBAC pattern.
export function NotificationsTab({ role, alertEmail }: { role: string | null; alertEmail: string | null }) {
  const [data, setData] = useState<AlertSentList | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [testState, setTestState] = useState<"idle" | "sending" | "sent" | "failed">("idle");
  const [testMessage, setTestMessage] = useState<string | null>(null);

  const LIMIT = 25;
  const canSendTest = role === "owner" || role === "admin";
  const canManageAlerts = role === "owner" || role === "admin";

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/alerts?page=${page}&limit=${LIMIT}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setData(d); })
      .finally(() => setLoading(false));
  }, [page]);

  useEffect(() => { load(); }, [load]);

  async function handleSendTest() {
    setTestState("sending");
    setTestMessage(null);
    try {
      const r = await apiFetch(`/alerts/test`, { method: "POST" });
      const d = await r.json().catch(() => ({}));
      setTestState(d.status === "sent" ? "sent" : "failed");
      setTestMessage(d.message ?? null);
    } catch {
      setTestState("failed");
      setTestMessage("Network error. Please try again.");
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / LIMIT)) : 1;

  return (
    <div>
      {/* Context line + test button, owner/admin only (viewer role has no
          settings visibility, so alertEmail is never resolvable for them). */}
      {canManageAlerts && (
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: "20px", flexWrap: "wrap", gap: "12px",
      }}>
        <p style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>
          {alertEmail
            ? <>Sending alerts to: <span style={{ color: "var(--color-text)", fontFamily: "var(--font-mono)" }}>{alertEmail}</span>{" "}
                <Link href="/dashboard/settings#alerts" style={{ color: "var(--color-text-muted)" }}>Change in Settings →</Link></>
            : <>No alert email configured. <Link href="/dashboard/settings#alerts" style={{ color: "var(--color-text)" }}>Set one up →</Link></>
          }
        </p>
        {canSendTest && (
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <button
              onClick={handleSendTest}
              disabled={testState === "sending" || !alertEmail}
              style={{
                padding: "7px 16px", fontSize: "12px",
                border: "1px solid var(--color-text)",
                background: "var(--color-text)", color: "var(--color-bg)",
                cursor: testState === "sending" ? "default" : "pointer",
                opacity: (testState === "sending" || !alertEmail) ? 0.6 : 1,
              }}
            >
              {testState === "sending" ? "Sending…" : "Send test alert"}
            </button>
            {testMessage && (
              <span style={{ fontSize: "12px", color: testState === "sent" ? "var(--color-low)" : "var(--color-critical)" }}>
                {testMessage}
              </span>
            )}
          </div>
        )}
      </div>
      )}

      {/* Table */}
      <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)" }}>
        {loading ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>Loading…</p>
        ) : !data || data.items.length === 0 ? (
          <p style={{ padding: "32px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>
            No alert emails sent yet.
          </p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr>
                {["Sent", "IP", "Severity", "Threat", "Status"].map(h => (
                  <th key={h} style={{
                    padding: "10px 16px", textAlign: "left", fontSize: "11px",
                    textTransform: "uppercase", letterSpacing: "0.06em",
                    color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", fontWeight: 500,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map(a => (
                <tr key={a.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                  <td style={{ padding: "10px 16px", color: "var(--color-text-muted)", whiteSpace: "nowrap", fontSize: "12px" }}>
                    {fmtTime(a.sent_at)}
                  </td>
                  <td style={{ padding: "10px 16px", fontFamily: "var(--font-mono)", fontSize: "12px" }}>
                    {a.verdict_ip ?? "—"}
                  </td>
                  <td style={{ padding: "10px 16px", color: "var(--color-text-muted)", textTransform: "capitalize" }}>
                    {a.verdict_severity ?? "—"}
                  </td>
                  <td style={{ padding: "10px 16px", color: "var(--color-text-muted)" }}>
                    {a.verdict_threat_type ?? "—"}
                  </td>
                  <td style={{ padding: "10px 16px" }} title={a.delivery_error ?? undefined}>
                    <span style={{
                      padding: "2px 6px", fontSize: "10px", fontWeight: 600,
                      letterSpacing: "0.06em", textTransform: "uppercase",
                      color: "#fff", background: STATUS_COLOR[a.status] ?? "#888",
                    }}>
                      {a.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "16px" }}>
          <button
            disabled={page <= 1}
            onClick={() => setPage(p => p - 1)}
            style={{ padding: "6px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: page <= 1 ? "var(--color-text-muted)" : "var(--color-text)", cursor: page <= 1 ? "default" : "pointer" }}
          >
            ← Prev
          </button>
          <span style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>Page {page} of {totalPages}</span>
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
