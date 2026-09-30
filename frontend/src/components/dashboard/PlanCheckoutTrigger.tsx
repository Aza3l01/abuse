"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { loadRazorpayCheckout } from "@/lib/razorpay";
import { tierDisplayName } from "@/lib/pricing";

const PURCHASABLE_PLANS = ["starter", "growth", "pro"];
// Mirrors api/tiers.py's MANUAL_BLOCK_TIERS: every self-serve paid tier gets
// at least manual blocking, so all three need the Blocking Subscription
// Agreement accepted before checkout (api/routes/billing.py enforces this
// server-side too, this is only the same UI gate settings/page.tsx uses).
const MANUAL_BLOCK_TIERS = ["starter", "growth", "pro", "enterprise"];

interface OrgConfigForCheckout {
  role: string;
  tier: string;
  blocking_tos_accepted_at: string | null;
}

/**
 * Phase 4b, route B: a visitor who clicked a paid plan's CTA on the landing
 * page gets that plan carried through registration in sessionStorage. This
 * component, mounted once in dashboard/layout.tsx, reads it exactly once on
 * first dashboard load, attempts checkout for that plan, and clears the
 * stored value regardless of outcome so a refresh never reopens it. If
 * Razorpay isn't configured (true today) or anything else goes wrong, it
 * degrades to a plain dismissible notice, never a dead end.
 */
export function PlanCheckoutTrigger() {
  const [plan, setPlan] = useState<string | null>(null);
  const [stage, setStage] = useState<"idle" | "tos-confirm" | "working" | "notice">("idle");
  const [notice, setNotice] = useState<string | null>(null);

  function degrade() {
    setNotice(`Couldn't start checkout for ${tierDisplayName(plan)}. You're on the free Starter plan, upgrade anytime from Settings.`);
    setStage("notice");
  }

  function openUpgradeOrderCheckout(
    tier: string,
    key_id: string,
    order_id: string,
    order_amount: number,
    onVerified: () => void,
  ) {
    const rzp = new window.Razorpay({
      key: key_id,
      order_id,
      amount: order_amount,
      currency: "INR",
      name: "Clew",
      description: `Upgrade to ${tierDisplayName(tier)}, price difference`,
      theme: { color: "#0D0D0D" },
      config: { display: { sequence: ["block.upi", "block.card", "block.netbanking", "block.wallet"] } },
      handler: async (response: { razorpay_payment_id: string; razorpay_order_id: string; razorpay_signature: string }) => {
        try {
          const vr = await apiFetch(`/billing/razorpay/verify-upgrade-order`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(response),
          });
          if (vr.ok) {
            onVerified();
          } else {
            degrade();
          }
        } catch {
          degrade();
        }
      },
      modal: { ondismiss: () => degrade() },
    });
    rzp.open();
  }

  function openSubscriptionCheckout(tier: string, key_id: string, subscription_id: string) {
    const rzp = new window.Razorpay({
      key: key_id,
      subscription_id,
      name: "Clew",
      description: `${tierDisplayName(tier)} plan`,
      theme: { color: "#0D0D0D" },
      config: { display: { sequence: ["block.upi", "block.card", "block.netbanking", "block.wallet"] } },
      handler: async (response: { razorpay_payment_id: string; razorpay_subscription_id: string; razorpay_signature: string }) => {
        try {
          const vr = await apiFetch(`/billing/razorpay/verify-payment`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tier, ...response }),
          });
          if (vr.ok) {
            // Full reload so every tier-dependent piece of the dashboard
            // (trial/usage banners, settings, onboarding's free-tier gates)
            // picks up the new tier, matching DashboardGate's own precedent.
            window.location.href = "/dashboard?upgraded=1";
          } else {
            degrade();
          }
        } catch {
          degrade();
        }
      },
      modal: { ondismiss: () => degrade() },
    });
    rzp.open();
  }

  async function startCheckout(tier: string) {
    setStage("working");
    try {
      await loadRazorpayCheckout();
      const r = await apiFetch(`/billing/razorpay/create-subscription`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier, period: "monthly", gstin: null }),
      });
      if (!r.ok) {
        degrade();
        return;
      }
      const { subscription_id, key_id, upgrade_order_id, upgrade_order_amount } = await r.json();
      if (upgrade_order_id) {
        openUpgradeOrderCheckout(tier, key_id, upgrade_order_id, upgrade_order_amount, () =>
          openSubscriptionCheckout(tier, key_id, subscription_id)
        );
      } else {
        openSubscriptionCheckout(tier, key_id, subscription_id);
      }
    } catch {
      degrade();
    }
  }

  useEffect(() => {
    let stored: string | null = null;
    try { stored = sessionStorage.getItem("clew_plan"); } catch { /* storage unavailable */ }
    if (!stored) return;
    try { sessionStorage.removeItem("clew_plan"); } catch { /* best effort */ }
    if (!PURCHASABLE_PLANS.includes(stored)) return;
    setPlan(stored);

    apiFetch(`/clients/me`)
      .then(r => r.ok ? r.json() : null)
      .then((c: OrgConfigForCheckout | null) => {
        if (!c || c.role !== "owner" || c.tier !== "free") return;
        if (MANUAL_BLOCK_TIERS.includes(stored!) && !c.blocking_tos_accepted_at) {
          setStage("tos-confirm");
        } else {
          startCheckout(stored!);
        }
      })
      .catch(() => {/* not an owner of a free org, or not reachable, skip silently */});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function acceptTosAndContinue() {
    if (!plan) return;
    setStage("working");
    try {
      const r = await apiFetch(`/clients/me/accept-blocking-tos`, { method: "POST" });
      if (!r.ok) {
        setNotice(`Couldn't start checkout for ${tierDisplayName(plan)}. You're on the free Starter plan, upgrade anytime from Settings.`);
        setStage("notice");
        return;
      }
      startCheckout(plan);
    } catch {
      setNotice(`Couldn't start checkout for ${tierDisplayName(plan)}. You're on the free Starter plan, upgrade anytime from Settings.`);
      setStage("notice");
    }
  }

  if (stage === "tos-confirm" && plan) {
    return (
      <div style={{
        position: "fixed", inset: 0, background: "rgba(13,13,13,0.6)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
      }}>
        <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", padding: "24px", maxWidth: "460px", width: "90%" }}>
          <p style={{ fontSize: "14px", fontWeight: 600, marginBottom: "12px" }}>
            This plan includes active IP blocking
          </p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "10px", lineHeight: 1.5 }}>
            Clew will add malicious IPs to your AWS WAF and Cloudflare account
            when you block them, whether manually or automatically depending
            on your plan. This is an active security action, not just monitoring.
          </p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "20px", lineHeight: 1.5 }}>
            By continuing, you accept the{" "}
            <a href="/legal/subscription-agreement" target="_blank" style={{ color: "var(--color-text)" }}>
              Blocking Subscription Agreement ↗
            </a>.
          </p>
          <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
            <button
              onClick={() => setStage("idle")}
              style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
            >
              Stay on free Starter
            </button>
            <button
              onClick={acceptTosAndContinue}
              style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-text)", background: "var(--color-text)", color: "var(--color-bg)", cursor: "pointer" }}
            >
              I understand, continue to payment
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (stage === "notice" && notice) {
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
          onClick={() => setStage("idle")}
          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", fontSize: "13px", padding: 0 }}
        >
          ×
        </button>
      </div>
    );
  }

  // "working" (checkout script/modal is taking over) and "idle" (nothing to do): render nothing.
  return null;
}
