"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { LoadingCursor } from "@/components/dashboard/LoadingCursor";

interface WouldHaveBlockedRow {
  id: string;
  ip: string;
  threat_type: string | null;
  severity: string;
  confidence: number;
  would_have_blocked_at: string | null;
}

const monoStyle: React.CSSProperties = { fontFamily: "var(--font-geist-mono, monospace)" };

const thStyle: React.CSSProperties = {
  padding: "10px 16px", textAlign: "left", fontSize: "11px", textTransform: "uppercase",
  letterSpacing: "0.06em", color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", fontWeight: 500,
};

// Phase 8 dry-run list: the 50 most recent verdicts automatic blocking would
// have blocked. `refreshKey` changes when the dry-run switch is saved so the
// table reloads.
export function WouldHaveBlockedTable({ refreshKey }: { refreshKey: boolean }) {
  const [rows, setRows] = useState<WouldHaveBlockedRow[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`/verdicts/would-have-blocked?limit=50`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error("API error"))))
      .then((d: WouldHaveBlockedRow[]) => { if (!cancelled) { setRows(d); setFailed(false); } })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  return (
    <div style={{ marginTop: "20px" }}>
      <h3 style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "8px" }}>
        Would have blocked
      </h3>
      <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)", overflowX: "auto" }}>
        {failed ? (
          <p style={{ padding: "24px 20px", fontSize: "13px", color: "var(--color-critical)", textAlign: "center" }}>
            Could not load this list.
          </p>
        ) : rows === null ? (
          <p style={{ padding: "24px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>
            Loading<LoadingCursor />
          </p>
        ) : rows.length === 0 ? (
          <p style={{ padding: "24px 20px", fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center" }}>
            Nothing yet. Entries appear here while dry run is on and a detection reaches your block threshold.
          </p>
        ) : (
          <table style={{ width: "100%", minWidth: "560px", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr>
                {["IP", "Threat", "Confidence", "When"].map(h => <th key={h} style={thStyle}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                  <td style={{ padding: "10px 16px", ...monoStyle }}>{row.ip}</td>
                  <td style={{ padding: "10px 16px" }}>{row.threat_type ?? "Unknown"}</td>
                  <td style={{ padding: "10px 16px", ...monoStyle }}>{Math.round(row.confidence * 100)}%</td>
                  <td style={{ padding: "10px 16px", ...monoStyle }}>
                    {row.would_have_blocked_at ? new Date(row.would_have_blocked_at).toLocaleString() : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
