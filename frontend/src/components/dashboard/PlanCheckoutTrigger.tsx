"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { PurchaseDialog } from "@/components/dashboard/PurchaseDialog";
import { tierDisplayName } from "@/lib/pricing";

const PURCHASABLE_PLANS = ["starter", "growth", "pro"];

interface OrgConfigForCheckout {
  role: string;
  tier: string;
  blocking_tos_accepted_at: string | null;
}

interface CheckoutContext {
  plan: string;
  lockedCountry: string | null;
  gstin: string | null;
  blockingTosAccepted: boolean;
}

/**
 * A visitor who clicked a paid plan's CTA on the landing page gets that plan
 * carried through registration in sessionStorage. This component, mounted
 * once in dashboard/layout.tsx, reads it exactly once on first dashboard
 * load and opens the same checkout dialog the billing section uses (monthly,
 * the dialog asks for the billing country and the agreements). The stored
 * value is cleared regardless of outcome so a refresh never reopens it. If
 * anything goes wrong it degrades to a plain dismissible notice, never a
 * dead end.
 */
export function PlanCheckoutTrigger() {
  const [ctx, setCtx] = useState<CheckoutContext | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function skipNotice(tier: string | null) {
    setNotice(`You're on the free Starter plan. Choose ${tierDisplayName(tier)} anytime from Settings, Billing.`);
  }

  useEffect(() => {
    let stored: string | null = null;
    try { stored = sessionStorage.getItem("clew_plan"); } catch { /* storage unavailable */ }
    if (!stored) return;
    try { sessionStorage.removeItem("clew_plan"); } catch { /* best effort */ }
    if (!PURCHASABLE_PLANS.includes(stored)) return;
    const plan = stored;

    Promise.all([
      apiFetch(`/clients/me`).then(r => r.ok ? r.json() : null),
      apiFetch(`/billing/status`).then(r => r.ok ? r.json() : null),
    ])
      .then(([c, b]: [OrgConfigForCheckout | null, { billing_country: string | null; billing_details: { gstin: string | null } } | null]) => {
        if (!c || !b || c.role !== "owner" || c.tier !== "free") return;
        setCtx({
          plan,
          lockedCountry: b.billing_country,
          gstin: b.billing_details?.gstin ?? null,
          blockingTosAccepted: !!c.blocking_tos_accepted_at,
        });
      })
      .catch(() => {/* not an owner of a free org, or not reachable, skip silently */});
  }, []);

  if (ctx) {
    const plan = ctx.plan;
    return (
      <PurchaseDialog
        target={{
          purpose: "initial",
          title: `Subscribe to ${tierDisplayName(plan)} (monthly)`,
          tier: plan,
          period: "monthly",
        }}
        lockedCountry={ctx.lockedCountry}
        savedGstin={ctx.gstin}
        blockingTosAccepted={ctx.blockingTosAccepted}
        trialActive={false}
        onClose={() => { setCtx(null); skipNotice(plan); }}
        onPaid={() => {
          // Full reload so every tier-dependent piece of the dashboard
          // (banners, settings, onboarding's free-tier gates) picks up the new
          // tier, matching DashboardGate's own precedent.
          window.location.href = "/?upgraded=1";
        }}
      />
    );
  }

  if (notice) {
    return (
      <div style={{
        margin: "0 32px", marginTop: "12px",
        padding: "10px 16px",
        border: "1px solid var(--color-border)",
        background: "var(--color-surface)",
        fontSize: "12px",
        color: "var(--color-text-muted)",
        display: "flex", justifyContent: "space-between", alignItems: "center", gap: "12px",
      }}>
        <span>{notice}</span>
        <button
          onClick={() => setNotice(null)}
          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", fontSize: "13px", padding: 0 }}
        >
          ×
        </button>
      </div>
    );
  }

  return null;
}
