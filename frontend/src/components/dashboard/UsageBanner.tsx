"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

interface UsageStatus {
  monthly_requests_processed: number;
  monthly_requests_cap: number | null;
}

/**
 * Item 30 (section 5) soft limits: amber banner at 80% of the tier's
 * monthly call volume, persistent red banner at 100%+. Scanning is never
 * paused by this, purely informational (an email is also sent once per
 * threshold per billing month, see send_quota_warning_email). Hidden
 * entirely for enterprise (no fixed cap) and for any org under 80%.
 */
export function UsageBanner() {
  const [status, setStatus] = useState<UsageStatus | null>(null);

  useEffect(() => {
    apiFetch(`/dashboard/summary?days=1`)
      .then((res) => (res.ok ? res.json() : null))
      .then(setStatus)
      .catch(() => {});
  }, []);

  if (!status || !status.monthly_requests_cap) return null;

  const percent = status.monthly_requests_processed / status.monthly_requests_cap;
  if (percent < 0.8) return null;

  const exceeded = percent >= 1;
  const accentColor = exceeded ? "var(--color-critical)" : "var(--color-high)";
  const used = status.monthly_requests_processed.toLocaleString("en-US");
  const cap = status.monthly_requests_cap.toLocaleString("en-US");

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "16px",
        padding: "12px 24px",
        borderBottom: `1px solid ${accentColor}`,
        background: "var(--color-surface)",
        fontSize: "13px",
        color: accentColor,
      }}
    >
      <span>
        {exceeded
          ? `You've reached your monthly call volume (${used} / ${cap}). Clew keeps scanning regardless.`
          : `You're at ${Math.floor(percent * 100)}% of your monthly call volume (${used} / ${cap}).`}
      </span>
      <Link
        href="/dashboard/settings#billing"
        style={{ color: accentColor, textDecoration: "underline", flexShrink: 0 }}
      >
        Upgrade plan →
      </Link>
    </div>
  );
}
