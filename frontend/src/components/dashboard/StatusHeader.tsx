"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Item 17: worker health / last-scanned timestamp. Item 16: S3 connection
// health dot. Both "live in the dashboard header, always visible" per their
// spec, so this mounts once in dashboard/layout.tsx rather than per-page.
// ---------------------------------------------------------------------------

interface StatusSummary {
  s3_configured: boolean;
  s3_status: string | null;
  last_scan_completed_at: string | null;
  last_scan_status: string | null;
}

function minutesAgo(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
}

function ScanStatus({ s }: { s: StatusSummary }) {
  if (s.last_scan_status === "error") {
    return (
      <Link href="/dashboard/settings#s3" style={{ color: "var(--color-critical)", textDecoration: "none", fontSize: "12px" }}>
        Last scan failed, check settings
      </Link>
    );
  }
  if (!s.last_scan_completed_at) {
    return <span style={{ color: "var(--color-text-muted)", fontSize: "12px" }}>Scan pending…</span>;
  }
  const mins = minutesAgo(s.last_scan_completed_at);
  const label = mins < 60
    ? `Last scanned: ${mins} minute${mins === 1 ? "" : "s"} ago`
    : `Scan overdue, last completed ${Math.floor(mins / 60)}h ${mins % 60}m ago`;
  const color = mins < 20 ? "var(--color-text-muted)" : mins <= 60 ? "var(--color-medium)" : "var(--color-high)";
  return <span style={{ color, fontSize: "12px" }}>{label}</span>;
}

export function StatusHeader() {
  const [summary, setSummary] = useState<StatusSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`/dashboard/summary?days=7`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (!cancelled && d) setSummary(d); })
      .catch(() => {/* header is non-critical */});
    return () => { cancelled = true; };
  }, []);

  if (!summary || !summary.s3_configured) return null;

  const dotColor = summary.s3_status === "error" ? "var(--color-critical)" : "var(--color-low)";
  const dotLabel = summary.s3_status === "error" ? "S3 error" : "S3 active";

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "flex-end",
      gap: "16px",
      padding: "10px 32px",
      borderBottom: "1px solid var(--color-border)",
      background: "var(--color-surface)",
    }}>
      <ScanStatus s={summary} />
      <Link
        href="/dashboard/settings#s3"
        style={{ display: "flex", alignItems: "center", gap: "6px", textDecoration: "none" }}
      >
        <span style={{ width: "8px", height: "8px", background: dotColor, display: "inline-block" }} />
        <span style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>{dotLabel}</span>
      </Link>
    </div>
  );
}
