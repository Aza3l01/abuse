// Shared billing types, money and date formatting, and the one checkout runner
// every Pay button goes through (plan purchase, upgrade, open bill, restore).
//
// Amounts are minor units (paise or cents) of the stated currency, exactly as
// the API returns them. The price is always computed on the server: the dialog
// shows a /billing/quote answer and create-order charges the same number.
import { apiFetch } from "@/lib/api";
import { loadRazorpayCheckout } from "@/lib/razorpay";
import { PRICING_TIERS, tierDisplayName, type PricingTier } from "@/lib/pricing";

export type Currency = "INR" | "USD";
export type Period = "monthly" | "annual";
export type PurchasePurpose = "initial" | "upgrade" | "bill" | "restore";

export interface BillSummary {
  id: string;
  tier: string;
  period: string;
  period_start: string;
  period_end: string;
  amount_paise: number;
  currency: Currency;
  due_date: string;
  cancel_on: string;
}

export interface PaymentRow {
  id: string;
  purpose: string;
  description: string | null;
  amount_paise: number;
  currency: Currency;
  status: string;
  created_at: string | null;
  captured_at: string | null;
  refunded_at: string | null;
}

export interface BillingDetails {
  legal_name: string | null;
  address: string | null;
  gstin: string | null;
  billing_country: string | null;
}

export interface RefundEligibility {
  eligible: boolean;
  reason: string;
  window_expires_at: string | null;
}

export interface BillingStatus {
  tier: string;
  billing_currency: Currency;
  billing_country: string | null;
  trial_source: string | null;
  trial_ends_at: string | null;
  billing_provider: string | null;
  payment_method_display: string | null;
  next_billing_date: string | null;
  next_bill_amount_paise: number | null;
  next_bill_plan: string | null;
  billing_period: Period | null;
  cancel_at_period_end: boolean;
  pending_tier: string | null;
  pending_period: Period | null;
  nonpayment_downgraded_at: string | null;
  retention_grace_until: string | null;
  open_bills: BillSummary[];
  payments: PaymentRow[];
  billing_details: BillingDetails;
  refund: RefundEligibility;
}

export interface BannerData {
  tier: string;
  role: string;
  billing_currency: Currency;
  billing_provider: string | null;
  billing_period: string | null;
  trial_ends_at: string | null;
  next_billing_date: string | null;
  cancel_at_period_end: boolean;
  nonpayment_downgraded_at: string | null;
  retention_grace_until: string | null;
  today_ist: string;
  open_bills: BillSummary[];
}

export interface Quote {
  amount: number;
  currency: Currency;
  billing_country: string | null;
  description: string;
}

export interface CheckoutRequest {
  purpose: PurchasePurpose;
  tier?: string;
  period?: Period;
  bill_id?: string;
  accept_blocking_tos?: boolean;
  accept_annual_nonrefundable?: boolean;
  gstin?: string | null;
  billing_country?: string | null;
}

/** Fired after a payment or plan change so the banner and billing section reload. */
export const BILLING_CHANGED_EVENT = "clew:billing-changed";

export function notifyBillingChanged(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(BILLING_CHANGED_EVENT));
}

// --- formatting -------------------------------------------------------------

export function formatMoney(minor: number, currency: string): string {
  const major = minor / 100;
  const whole = Number.isInteger(major);
  const locale = currency === "INR" ? "en-IN" : "en-US";
  const digits = new Intl.NumberFormat(locale, {
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(major);
  return `${currency === "INR" ? "₹" : "$"}${digits}`;
}

/** Date-only strings ("2026-11-20", bills) are calendar dates and show as is.
 * Timestamps show in IST by default (billing runs on the IST calendar), or in
 * the browser's zone with local: true (payment times). */
export function formatDate(iso: string | null | undefined, opts: { local?: boolean } = {}): string {
  if (!iso) return "—";
  const dateOnly = iso.length === 10;
  const d = new Date(dateOnly ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: dateOnly ? "UTC" : opts.local ? undefined : "Asia/Kolkata",
  });
}

/** Whole days from today_ist (a date string) to a date-only string. Negative
 * when the date is past. */
export function daysFromToday(todayIst: string, date: string): number {
  const a = Date.parse(`${todayIst.slice(0, 10)}T00:00:00Z`);
  const b = Date.parse(`${date.slice(0, 10)}T00:00:00Z`);
  return Math.round((b - a) / 86400000);
}

export function planLabel(tier: string | null | undefined, period?: string | null): string {
  const name = tierDisplayName(tier);
  return period ? `${name} ${period}` : name;
}

/** Display price of a plan for a currency, from lib/pricing.ts (the same
 * strings as the public page). The charged amount always comes from a quote. */
export function displayPrice(
  tier: PricingTier,
  currency: Currency,
  period: Period,
): { price: string | null; note: string | null } {
  if (period === "monthly") {
    return { price: currency === "INR" ? tier.monthlyINR : tier.monthlyUSD, note: null };
  }
  return {
    price: currency === "INR" ? tier.annualINR : tier.annualUSD,
    note: currency === "INR" ? tier.annualNoteINR : tier.annualNoteUSD,
  };
}

export const PURCHASABLE_TIERS: PricingTier[] = PRICING_TIERS.filter(
  (t) => t.tier === "starter" || t.tier === "growth" || t.tier === "pro",
);

const TIER_RANK: Record<string, number> = { free: 0, starter: 1, growth: 2, pro: 3, enterprise: 4 };

export function tierRank(tier: string | null | undefined): number {
  return tier ? (TIER_RANK[tier] ?? 0) : 0;
}

export type ChangeKind = "upgrade" | "downgrade" | "same" | "unsupported";

/** Mirrors api/billing_rules.py classify_change, only to label buttons. The
 * server decides what is allowed. Changing the tier and the period together
 * is not supported, one change at a time. */
export function classifyChange(
  oldTier: string,
  oldPeriod: string,
  newTier: string,
  newPeriod: string,
): ChangeKind {
  if (oldTier === newTier && oldPeriod === newPeriod) return "same";
  if (oldTier !== newTier && oldPeriod !== newPeriod) return "unsupported";
  if (oldTier === newTier) return oldPeriod === "monthly" && newPeriod === "annual" ? "upgrade" : "downgrade";
  return tierRank(newTier) > tierRank(oldTier) ? "upgrade" : "downgrade";
}

/** The IST calendar date (YYYY-MM-DD) of a timestamp. */
export function istDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

// --- errors -----------------------------------------------------------------

/** FastAPI errors are { detail: string } or { detail: { message, ... } }. */
export async function errorText(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => null);
  const detail = data?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.message === "string") return detail.message;
  if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  return fallback;
}

// --- checkout ---------------------------------------------------------------

export type CheckoutResult =
  | { kind: "paid" }
  | { kind: "dismissed" }
  | { kind: "error"; message: string };

interface CreateOrderResponse {
  order_id: string;
  amount: number;
  currency: Currency;
  key_id: string;
  payment_id: string;
}

/** create-order, Razorpay Checkout, verify-payment. Never throws. */
export async function runCheckout(req: CheckoutRequest, description: string): Promise<CheckoutResult> {
  let order: CreateOrderResponse;
  try {
    await loadRazorpayCheckout();
    const r = await apiFetch(`/billing/razorpay/create-order`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) return { kind: "error", message: await errorText(r, "Could not start checkout. Please try again.") };
    order = await r.json();
  } catch {
    return { kind: "error", message: "Could not start checkout. Check your connection and try again." };
  }

  const options: Record<string, unknown> = {
    key: order.key_id,
    order_id: order.order_id,
    amount: order.amount,
    currency: order.currency,
    name: "Clew",
    description,
    theme: { color: "#0D0D0D" },
  };
  // Indian orders keep the full method list. USD orders set no sequence, so
  // Checkout shows only what Razorpay allows for that currency (cards).
  if (order.currency === "INR") {
    options.config = { display: { sequence: ["block.upi", "block.card", "block.netbanking", "block.wallet"] } };
  }

  return new Promise<CheckoutResult>((resolve) => {
    let settled = false;
    let paying = false;
    const finish = (r: CheckoutResult) => {
      if (settled) return;
      settled = true;
      resolve(r);
    };
    options.handler = async (response: {
      razorpay_payment_id: string;
      razorpay_order_id: string;
      razorpay_signature: string;
    }) => {
      paying = true;
      try {
        const vr = await apiFetch(`/billing/razorpay/verify-payment`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(response),
        });
        notifyBillingChanged();
        if (vr.ok) {
          finish({ kind: "paid" });
        } else {
          finish({
            kind: "error",
            message: await errorText(
              vr,
              "Your payment went through but is not confirmed yet. Refresh in a minute, or contact support@clewsec.com if it does not show.",
            ),
          });
        }
      } catch {
        finish({
          kind: "error",
          message: "Your payment went through but is not confirmed yet. Refresh in a minute, or contact support@clewsec.com if it does not show.",
        });
      }
    };
    options.modal = { ondismiss: () => { if (!paying) finish({ kind: "dismissed" }); } };
    try {
      new window.Razorpay(options).open();
    } catch {
      finish({ kind: "error", message: "Could not open the payment window. Please try again." });
    }
  });
}
