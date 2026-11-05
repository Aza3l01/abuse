"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

interface ReferralStatus {
  referral_code: string | null;
  slots_filled: number;
  slots_total: number;
  is_referred: boolean;
  discount_pct_monthly: number;
  discount_pct_annual: number;
}

function formatPct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

/**
 * TODO.md priority item 5: referral/pilot code system. Shows this org's own
 * shareable invite link, live slot progress out of 5, and the currently
 * applicable discount for each billing period, including the flat
 * referred-org discount if this org itself signed up via someone else's
 * code. Owner-only, matches every other billing-adjacent dashboard section
 * (GET /billing/referral-status is owner-gated the same as /billing/status).
 * Everything here is read live on every load, never cached client-side.
 */
export function ReferralSection({ myRole }: { myRole: string | null }) {
  const [status, setStatus] = useState<ReferralStatus | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (myRole !== "owner") return;
    apiFetch(`/billing/referral-status`)
      .then((res) => (res.ok ? res.json() : null))
      .then(setStatus)
      .catch(() => setStatus(null));
  }, [myRole]);

  if (myRole !== "owner" || !status) return null;

  const inviteLink = status.referral_code
    ? `https://www.clewsec.com/register?ref=${status.referral_code}`
    : null;

  function copyLink() {
    if (!inviteLink) return;
    navigator.clipboard.writeText(inviteLink).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div style={{ border: "1px solid var(--color-border)", padding: "20px", background: "var(--color-bg)" }}>
      {status.is_referred && (
        <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "16px" }}>
          Your organisation was referred, you get a flat {formatPct(status.discount_pct_monthly)}
          {" "}discount on monthly plans ({formatPct(status.discount_pct_annual)} on annual), included
          in the totals below.
        </p>
      )}

      <p style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "8px" }}>
        Referral slots
      </p>
      <div style={{ display: "flex", gap: "4px", marginBottom: "8px" }}>
        {Array.from({ length: status.slots_total }).map((_, i) => (
          <div
            key={i}
            style={{
              width: "28px",
              height: "28px",
              border: "1px solid var(--color-border)",
              background: i < status.slots_filled ? "var(--color-text)" : "transparent",
            }}
          />
        ))}
      </div>
      <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "20px" }}>
        {status.slots_filled}/{status.slots_total} referred organisations currently paying. Each
        filled slot adds a discount, a slot frees up immediately if that organisation cancels.
      </p>

      <div style={{ display: "flex", justifyContent: "space-between", gap: "16px", flexWrap: "wrap", marginBottom: "16px" }}>
        <div>
          <p style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "4px" }}>
            Monthly discount
          </p>
          <p style={{ fontSize: "18px", fontFamily: "var(--font-brand)", fontWeight: 700 }}>
            {formatPct(status.discount_pct_monthly)}
          </p>
        </div>
        <div>
          <p style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "4px" }}>
            Annual discount
          </p>
          <p style={{ fontSize: "18px", fontFamily: "var(--font-brand)", fontWeight: 700 }}>
            {formatPct(status.discount_pct_annual)}
          </p>
        </div>
      </div>

      {inviteLink && (
        <div>
          <p style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "8px" }}>
            Your invite link
          </p>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <input
              readOnly
              value={inviteLink}
              onFocus={(e) => e.target.select()}
              style={{
                flex: 1,
                minWidth: "220px",
                padding: "7px 10px",
                fontSize: "12px",
                fontFamily: "var(--font-mono)",
                border: "1px solid var(--color-border)",
                background: "var(--color-surface)",
                color: "var(--color-text)",
              }}
            />
            <button
              onClick={copyLink}
              style={{
                padding: "7px 16px",
                fontSize: "12px",
                border: "1px solid var(--color-border)",
                background: "transparent",
                color: "var(--color-text)",
                cursor: "pointer",
              }}
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
