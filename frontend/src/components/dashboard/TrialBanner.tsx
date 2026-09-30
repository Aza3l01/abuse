"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

interface BillingStatus {
  trial_source: string | null;
  trial_ends_at: string | null;
  billing_provider: string | null;
}

/**
 * Item 53 (section 4): Growth-pilot-only now. Only an org onboarded with a
 * promo code ever has trial_ends_at set (self-serve signups land directly
 * on the free Starter tier, no trial at all), so this banner is naturally
 * hidden for every org that never had one. Persistent (non-dismissible),
 * owner-only, since GET /billing/status is owner-only (item 8: admin/viewer
 * have no billing visibility at all). Hidden once a payment method is on
 * file.
 */
export function TrialBanner() {
  const [status, setStatus] = useState<BillingStatus | null>(null);

  useEffect(() => {
    apiFetch(`/billing/status`)
      .then((res) => (res.ok ? res.json() : null))
      .then(setStatus)
      .catch(() => {});
  }, []);

  if (!status || !status.trial_ends_at) return null;
  if (status.billing_provider === "stripe" || status.billing_provider === "razorpay") return null;

  const endsAt = new Date(status.trial_ends_at);
  const daysRemaining = Math.ceil((endsAt.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  const expired = daysRemaining <= 0;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "16px",
        padding: "12px 24px",
        borderBottom: "1px solid var(--color-border)",
        background: "var(--color-surface)",
        fontSize: "13px",
        color: "var(--color-text)",
      }}
    >
      <span>
        {expired
          ? "Your Growth trial has ended. You've been moved to the free Starter plan, add a payment method to get Growth back."
          : `Growth trial: ${daysRemaining} day${daysRemaining === 1 ? "" : "s"} remaining.`}
      </span>
      <Link
        href="/dashboard/settings#billing"
        style={{ color: "var(--color-text)", textDecoration: "underline", flexShrink: 0 }}
      >
        Add payment method →
      </Link>
    </div>
  );
}
