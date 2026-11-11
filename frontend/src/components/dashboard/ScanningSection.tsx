"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";
import { SCANNING_CHANGED_EVENT } from "@/components/dashboard/StatusHeader";

interface Props {
  role: string | null;
  pausedAt: string | null;
  onChanged: (pausedAt: string | null) => void;
}

const btn: React.CSSProperties = {
  padding: "8px 20px",
  fontSize: "13px",
  border: "1px solid var(--color-text)",
  background: "var(--color-text)",
  color: "var(--color-bg)",
  cursor: "pointer",
};

const ghostBtn: React.CSSProperties = {
  ...btn,
  background: "transparent",
  color: "var(--color-text)",
  border: "1px solid var(--color-border)",
};

/**
 * Phase 12b: owner/admin pause and resume of log scanning. While paused no
 * new logs are read. Resuming skips whatever arrived during the pause.
 * Renders nothing for a viewer (the header still shows the paused state).
 */
export function ScanningSection({ role, pausedAt, onChanged }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy]             = useState(false);
  const [error, setError]           = useState("");

  if (role !== "owner" && role !== "admin") return null;

  async function send(action: "pause" | "resume") {
    setBusy(true);
    setError("");
    try {
      const r = await apiFetch(`/org/scanning/${action}`, { method: "POST" });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setError(typeof d?.detail === "string" ? d.detail : "Could not update scanning. Try again.");
        return;
      }
      const d = await r.json();
      onChanged(d.scanning_paused_at ?? null);
      setConfirming(false);
      window.dispatchEvent(new Event(SCANNING_CHANGED_EVENT));
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {pausedAt ? (
        <>
          <p style={{ fontSize: "13px", marginBottom: "8px" }}>
            Scanning is paused. Clew is not reading logs.
          </p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "16px", lineHeight: 1.6 }}>
            When you resume, logs written during the pause are skipped. Scanning continues from new logs only.
          </p>
          <button style={{ ...btn, opacity: busy ? 0.6 : 1 }} disabled={busy} onClick={() => send("resume")}>
            {busy ? "Resuming…" : "Resume scanning"}
          </button>
        </>
      ) : (
        <>
          <p style={{ fontSize: "13px", marginBottom: "8px" }}>Scanning is running.</p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "8px", lineHeight: 1.6 }}>
            Pausing stops Clew from reading new logs. These are not affected:
          </p>
          <ul style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "0 0 16px 18px", lineHeight: 1.7 }}>
            <li>Verdicts that are already saved</li>
            <li>IPs you have already blocked, and manual block and unblock</li>
            <li>Alerts for earlier findings</li>
            <li>Your account and billing</li>
          </ul>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "16px", lineHeight: 1.6 }}>
            Pausing does not freeze your data. Data older than your plan&apos;s retention is still deleted on schedule.
          </p>
          {!confirming ? (
            <button style={ghostBtn} onClick={() => setConfirming(true)}>Pause scanning</button>
          ) : (
            <div style={{ border: "1px solid var(--color-border)", padding: "16px" }}>
              <p style={{ fontSize: "13px", marginBottom: "12px", lineHeight: 1.6 }}>
                Pause scanning for your whole team? Logs written while paused will be skipped when you resume.
              </p>
              <div style={{ display: "flex", gap: "8px" }}>
                <button style={{ ...btn, opacity: busy ? 0.6 : 1 }} disabled={busy} onClick={() => send("pause")}>
                  {busy ? "Pausing…" : "Pause scanning"}
                </button>
                <button style={ghostBtn} disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
              </div>
            </div>
          )}
        </>
      )}
      {error && <p style={{ fontSize: "12px", color: "var(--color-critical)", marginTop: "8px" }}>{error}</p>}
    </div>
  );
}
