"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import {
  BILLING_CHANGED_EVENT,
  daysFromToday,
  formatDate,
  formatMoney,
  planLabel,
  type BannerData,
} from "@/lib/billing";

type Level = "info" | "warning" | "alert";

interface BannerView {
  level: Level;
  label: string;
  text: string;
  action: string;
}

const LEVEL_COLOR: Record<Level, string> = {
  info: "var(--color-info)",
  warning: "var(--color-medium)",
  alert: "var(--color-critical)",
};

/**
 * Decides which billing banner (if any) to show. Pure on purpose: the date
 * logic uses today_ist from the API, never the browser clock, because bills
 * are due on IST calendar dates.
 */
export function bannerView(d: BannerData): BannerView | null {
  if (d.billing_provider === "stripe") return null;
  const bills = d.open_bills;
  if (bills.length === 0) return null;

  const total = bills.reduce((sum, b) => sum + b.amount_paise, 0);
  const amount = formatMoney(total, bills[0].currency);
  const first = bills[0];
  const noun = bills.length === 1 ? "bill" : `${bills.length} bills`;

  // Cancelled for non-payment with the bills still unpaid.
  if (d.tier === "free" && d.nonpayment_downgraded_at) {
    return {
      level: "alert",
      label: "Plan cancelled",
      text: `Your plan was cancelled because ${bills.length === 1 ? "a bill" : "bills"} (${amount}) went unpaid. Restore it to continue where you left off.`,
      action: "Restore plan",
    };
  }
  if (d.tier === "free") return null;

  const untilDue = daysFromToday(d.today_ist, first.due_date);
  const untilCancel = daysFromToday(d.today_ist, first.cancel_on);
  const plan = planLabel(first.tier, first.period);

  if (untilDue < 0 && untilCancel > 0) {
    return {
      level: "alert",
      label: "Overdue",
      text: `Your ${plan} ${noun} (${amount}) was due ${formatDate(first.due_date)}. Your plan is cancelled on ${formatDate(first.cancel_on)} if it stays unpaid.`,
      action: "Pay now",
    };
  }
  if (untilDue >= 0 && untilDue <= 3) {
    return {
      level: "warning",
      label: "Due soon",
      text: `Your ${plan} ${noun} (${amount}) is due ${untilDue === 0 ? "today" : `on ${formatDate(first.due_date)}`}.`,
      action: "Pay now",
    };
  }
  if (untilDue > 3) {
    return {
      level: "info",
      label: "Bill ready",
      text: `Your ${plan} ${noun} (${amount}) is ready. Pay by ${formatDate(first.due_date)}.`,
      action: "Pay now",
    };
  }
  return null;
}

/**
 * Billing state banner for every role. Owners get a link to the billing
 * section, other members see the same text and who to ask. Text only
 * (DESIGN_SYSTEM.md): a square border, the state word in a functional colour.
 */
export function BillingBanner() {
  const [data, setData] = useState<BannerData | null>(null);

  const load = useCallback(() => {
    apiFetch(`/billing/banner`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: BannerData | null) => setData(d))
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const onVisible = () => { if (document.visibilityState === "visible") load(); };
    window.addEventListener(BILLING_CHANGED_EVENT, load);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener(BILLING_CHANGED_EVENT, load);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);

  if (!data) return null;
  const view = bannerView(data);
  if (!view) return null;

  const isOwner = data.role === "owner";

  return (
    <div
      role="status"
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
        <span
          style={{
            color: LEVEL_COLOR[view.level],
            fontFamily: "var(--font-geist-mono, monospace)",
            fontSize: "11px",
            textTransform: "uppercase",
            letterSpacing: "0.07em",
            marginRight: "10px",
          }}
        >
          {view.label}
        </span>
        {view.text}
      </span>
      {isOwner ? (
        <Link
          href="/settings#billing"
          style={{ color: "var(--color-text)", textDecoration: "underline", flexShrink: 0 }}
        >
          {view.action} →
        </Link>
      ) : (
        <span style={{ color: "var(--color-text-muted)", flexShrink: 0 }}>
          Ask your organisation owner.
        </span>
      )}
    </div>
  );
}
