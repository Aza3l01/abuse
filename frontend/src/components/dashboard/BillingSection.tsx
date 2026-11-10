"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { COUNTRIES, countryName, guessBillingCountry } from "@/lib/countries";
import { FEATURE_ROWS, PRICING_TIERS, tierDisplayName, type PricingTier } from "@/lib/pricing";
import {
  PURCHASABLE_TIERS,
  classifyChange,
  displayPrice,
  errorText,
  formatDate,
  formatMoney,
  istDate,
  notifyBillingChanged,
  planLabel,
  type BillSummary,
  type BillingStatus,
  type Currency,
  type Period,
} from "@/lib/billing";
import { PurchaseDialog, type PurchaseTarget } from "@/components/dashboard/PurchaseDialog";

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 10px",
  fontSize: "13px",
  border: "1px solid var(--color-border)",
  background: "var(--color-surface)",
  color: "var(--color-text)",
  boxSizing: "border-box",
};

const cardStyle: React.CSSProperties = {
  border: "1px solid var(--color-border)",
  padding: "20px",
  background: "var(--color-bg)",
  marginBottom: "16px",
};

const labelStyle: React.CSSProperties = {
  fontSize: "11px",
  color: "var(--color-text-muted)",
  textTransform: "uppercase",
  letterSpacing: "0.07em",
  marginBottom: "4px",
};

const mutedStyle: React.CSSProperties = { fontSize: "12px", color: "var(--color-text-muted)", lineHeight: 1.5, margin: 0 };
const monoStyle: React.CSSProperties = { fontFamily: "var(--font-geist-mono, monospace)" };

const primaryButton = (disabled = false): React.CSSProperties => ({
  padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-text)",
  background: "var(--color-text)", color: "var(--color-bg)",
  cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.5 : 1,
});

const plainButton = (disabled = false): React.CSSProperties => ({
  padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)",
  background: "transparent", color: "var(--color-text)",
  cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.5 : 1,
});

const dangerButton = (disabled = false): React.CSSProperties => ({
  padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-critical)",
  background: "transparent", color: "var(--color-critical)",
  cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.5 : 1,
});

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: "14px" }}>
      <p style={labelStyle}>{label}</p>
      <div style={{ fontSize: "13px" }}>{children}</div>
    </div>
  );
}

function Confirm({
  title, body, confirmLabel, cancelLabel, danger, busy, onConfirm, onCancel,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel: string;
  danger?: boolean;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(13,13,13,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
    }}>
      <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", padding: "24px", maxWidth: "460px", width: "90%", animation: "modal-panel-in 150ms ease-out" }}>
        <p style={{ fontSize: "14px", fontWeight: 600, marginBottom: "12px" }}>{title}</p>
        <p style={{ ...mutedStyle, marginBottom: "20px" }}>{body}</p>
        <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
          <button onClick={onCancel} disabled={busy} style={plainButton(busy)}>{cancelLabel}</button>
          <button
            onClick={onConfirm}
            disabled={busy}
            style={danger
              ? { ...primaryButton(busy), background: "var(--color-critical)", border: "1px solid var(--color-critical)" }
              : primaryButton(busy)}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

type ConfirmKind = "cancel" | "refund" | { downgrade: { tier: string; period: Period } };

type StatusResult =
  | { kind: "denied" }
  | { kind: "failed" }
  | { kind: "ok"; status: BillingStatus };

async function fetchStatus(): Promise<StatusResult> {
  try {
    const r = await apiFetch(`/billing/status`);
    if (r.status === 403) return { kind: "denied" };
    if (!r.ok) return { kind: "failed" };
    return { kind: "ok", status: (await r.json()) as BillingStatus };
  } catch {
    return { kind: "failed" };
  }
}

function statusWord(s: string): string {
  if (s === "captured") return "Paid";
  if (s === "refunded") return "Refunded";
  if (s === "failed") return "Failed";
  return s;
}

/**
 * Plan and billing for the organisation owner: overview, open bills with Pay
 * now, plan changes, payment history with receipts, billing details. Every
 * payment runs through PurchaseDialog (create-order, Razorpay Checkout,
 * verify-payment). Prices on the cards are display strings from
 * lib/pricing.ts, the amount charged always comes from a server quote.
 */
export function BillingSection({
  blockingTosAccepted,
  onPlanChanged,
}: {
  blockingTosAccepted: boolean;
  onPlanChanged: () => void;
}) {
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [denied, setDenied] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [purchase, setPurchase] = useState<PurchaseTarget | null>(null);
  const [period, setPeriod] = useState<Period>("monthly");
  const [confirm, setConfirm] = useState<ConfirmKind | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // Billing details form
  const [legalName, setLegalName] = useState("");
  const [address, setAddress] = useState("");
  const [gstin, setGstin] = useState("");
  const [country, setCountry] = useState("");
  const [savingDetails, setSavingDetails] = useState(false);
  const [detailsMsg, setDetailsMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const applyStatus = useCallback((res: StatusResult) => {
    if (res.kind === "denied") { setDenied(true); return; }
    if (res.kind === "failed") { setLoadFailed(true); return; }
    const s = res.status;
    setStatus(s);
    setLoadFailed(false);
    setLegalName(s.billing_details.legal_name ?? "");
    setAddress(s.billing_details.address ?? "");
    setGstin(s.billing_details.gstin ?? "");
    setCountry(s.billing_details.billing_country ?? "");
  }, []);

  const load = useCallback(async () => {
    applyStatus(await fetchStatus());
  }, [applyStatus]);

  useEffect(() => {
    let cancelled = false;
    fetchStatus().then((res) => { if (!cancelled) applyStatus(res); });
    return () => { cancelled = true; };
  }, [applyStatus]);

  async function action(path: string, key: string, init: RequestInit = { method: "POST" }): Promise<Response | null> {
    setBusy(key);
    setNotice(null);
    try {
      const r = await apiFetch(path, init);
      if (!r.ok) {
        setNotice({ ok: false, text: await errorText(r, "That did not work. Please try again.") });
        return null;
      }
      return r;
    } catch {
      setNotice({ ok: false, text: "Network error. Please try again." });
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function refreshAll() {
    await load();
    onPlanChanged();
    notifyBillingChanged();
  }

  async function runConfirmed() {
    if (!confirm) return;
    let r: Response | null = null;
    let done = "";
    if (confirm === "cancel") {
      r = await action(`/billing/cancel`, "confirm");
      done = "Your plan will cancel at the end of the paid period.";
    } else if (confirm === "refund") {
      r = await action(`/billing/refund`, "confirm");
      done = "Refund issued. Your plan is now the free Starter plan.";
    } else {
      r = await action(`/billing/schedule-downgrade`, "confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(confirm.downgrade),
      });
      done = "Downgrade scheduled for your next bill.";
    }
    setConfirm(null);
    if (r) {
      setNotice({ ok: true, text: done });
      await refreshAll();
    }
  }

  async function undoPending() {
    const r = await action(`/billing/undo-pending`, "undo");
    if (r) {
      setNotice({ ok: true, text: "The scheduled change was withdrawn. Your plan carries on as it is." });
      await refreshAll();
    }
  }

  async function openPortal() {
    const r = await action(`/billing/portal`, "portal");
    if (r) {
      const { url } = await r.json();
      window.location.href = url;
    }
  }

  async function saveDetails(e: React.FormEvent) {
    e.preventDefault();
    if (!status) return;
    setSavingDetails(true);
    setDetailsMsg(null);
    const body: Record<string, string> = { legal_name: legalName, address };
    if (status.billing_currency === "INR" && status.billing_country) body.gstin = gstin;
    if (!status.billing_country && country) body.billing_country = country;
    try {
      const r = await apiFetch(`/billing/details`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        setDetailsMsg({ ok: false, text: await errorText(r, "Could not save billing details.") });
      } else {
        setDetailsMsg({ ok: true, text: "Saved." });
        await load();
      }
    } catch {
      setDetailsMsg({ ok: false, text: "Network error. Please try again." });
    } finally {
      setSavingDetails(false);
    }
  }

  if (denied) {
    return (
      <div style={cardStyle}>
        <p style={mutedStyle}>Billing is managed by your organisation owner. Ask them if you need a plan change or a receipt.</p>
      </div>
    );
  }
  if (loadFailed && !status) {
    return <div style={cardStyle}><p style={{ ...mutedStyle, color: "var(--color-critical)" }}>Could not load billing. Refresh the page to try again.</p></div>;
  }
  if (!status) {
    return <div style={cardStyle}><p style={mutedStyle}>Loading billing…</p></div>;
  }

  // ---- derived state -------------------------------------------------------
  const s = status;
  const stripeBilled = s.billing_provider === "stripe";
  const enterprise = s.tier === "enterprise";
  const onPaidPlan = !!s.billing_period && PURCHASABLE_TIERS.some(t => t.tier === s.tier);
  const pilot = !onPaidPlan && !stripeBilled && s.tier !== "starter" && !!s.trial_ends_at;
  const cancelled = s.tier === "starter" && !!s.nonpayment_downgraded_at;
  const latestBill: BillSummary | undefined = s.open_bills[s.open_bills.length - 1];
  const currency: Currency = s.billing_country
    ? s.billing_currency
    : guessBillingCountry() === "IN" ? "INR" : "USD";
  const pending = s.cancel_at_period_end || !!s.pending_tier || !!s.pending_period;
  const nextDate = s.next_billing_date ? istDate(s.next_billing_date) : null;
  const payBy = nextDate ? `${nextDate.slice(0, 8)}20` : null;
  const showPlanCards = !stripeBilled && !enterprise && !(cancelled && latestBill);

  function startPurchase(t: PricingTier, p: Period, purpose: "initial" | "upgrade") {
    setNotice(null);
    setPurchase({
      purpose,
      tier: t.tier,
      period: p,
      title: purpose === "upgrade"
        ? `Upgrade to ${t.name} (${p})`
        : `Subscribe to ${t.name} (${p})`,
    });
  }

  function cardAction(t: PricingTier): { label: string; disabled: boolean; hint?: string; onClick?: () => void } {
    if (!onPaidPlan) {
      return { label: "Choose plan", disabled: false, onClick: () => startPurchase(t, period, "initial") };
    }
    const kind = classifyChange(s.tier, s.billing_period as string, t.tier, period);
    if (kind === "same") return { label: "Current plan", disabled: true };
    if (kind === "unsupported") {
      return { label: "Change one thing at a time", disabled: true, hint: "Switch the plan, or the billing period, not both at once." };
    }
    if (kind === "upgrade") {
      return { label: "Upgrade", disabled: false, onClick: () => startPurchase(t, period, "upgrade") };
    }
    return {
      label: "Downgrade at next bill",
      disabled: false,
      onClick: () => setConfirm({ downgrade: { tier: t.tier, period } }),
    };
  }

  const confirmText = (() => {
    if (confirm === "cancel") {
      return {
        title: "Cancel your plan?",
        body: `Your plan stays active until the end of the period you have paid for${s.next_billing_date ? ` (${formatDate(s.next_billing_date)})` : ""}, then cancels. You will not be billed again. You can undo this before then.`,
        label: "Confirm cancellation", cancel: "Keep my plan", danger: true,
      };
    }
    if (confirm === "refund") {
      return {
        title: "Refund your first payment?",
        body: "You get a full refund and your plan drops to the free Starter plan straight away. This is only possible within 72 hours of your first payment.",
        label: "Refund and cancel", cancel: "Keep my plan", danger: true,
      };
    }
    if (confirm) {
      return {
        title: `Downgrade to ${planLabel(confirm.downgrade.tier, confirm.downgrade.period)}?`,
        body: `Your current plan stays active until the end of the paid period${s.next_billing_date ? ` (${formatDate(s.next_billing_date)})` : ""}. The new plan starts with your next bill. You can undo this before then.`,
        label: "Schedule downgrade", cancel: "Not now", danger: false,
      };
    }
    return null;
  })();

  return (
    <div>
      {notice && (
        <div style={{
          padding: "10px 14px",
          border: `1px solid ${notice.ok ? "var(--color-low)" : "var(--color-critical)"}`,
          marginBottom: "16px", fontSize: "12px",
          color: notice.ok ? "var(--color-low)" : "var(--color-critical)",
        }}>
          {notice.text}
        </div>
      )}

      {/* Overview */}
      <div style={cardStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "16px", flexWrap: "wrap", marginBottom: "14px" }}>
          <div>
            <p style={labelStyle}>Current plan</p>
            <p style={{ fontSize: "18px", fontFamily: "var(--font-brand)", fontWeight: 700, margin: 0 }}>
              {tierDisplayName(s.tier)}{onPaidPlan ? `, ${s.billing_period}` : ""}
            </p>
          </div>
          {stripeBilled && (
            <button onClick={openPortal} disabled={busy === "portal"} style={plainButton(busy === "portal")}>
              {busy === "portal" ? "Redirecting…" : "Manage billing"}
            </button>
          )}
        </div>

        {pilot && (
          <p style={{ ...mutedStyle, marginBottom: "14px" }}>
            Growth pilot{s.trial_ends_at ? `, trial ends ${formatDate(s.trial_ends_at)}` : ""}. Paying for a plan ends the trial.
          </p>
        )}
        {s.tier === "starter" && !cancelled && (
          <p style={{ ...mutedStyle, marginBottom: "14px" }}>
            You are on the free Starter plan. Choose a plan to unlock longer threat history, email alerts and blocking.
          </p>
        )}
        {enterprise && (
          <p style={{ ...mutedStyle, marginBottom: "14px" }}>
            Enterprise plans are managed by Clew.{" "}
            <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>Contact support</a> for billing questions.
          </p>
        )}

        {onPaidPlan && !stripeBilled && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "16px" }}>
            <Row label="Billing currency">
              {s.billing_currency}{s.billing_country ? `, ${countryName(s.billing_country)}` : ""}
            </Row>
            <Row label="Next bill">
              {s.next_bill_amount_paise !== null && s.next_bill_plan
                ? <><span style={monoStyle}>{formatMoney(s.next_bill_amount_paise, s.billing_currency)}</span>{`, ${s.next_bill_plan}`}</>
                : "Nothing will be billed"}
              {nextDate && <span style={{ color: "var(--color-text-muted)" }}>{` on ${formatDate(s.next_billing_date)}`}</span>}
            </Row>
            {s.next_bill_amount_paise !== null && payBy && (
              <Row label="Pay by">{formatDate(payBy)}</Row>
            )}
            {s.payment_method_display && <Row label="Last paid with">{s.payment_method_display}</Row>}
          </div>
        )}

        {s.cancel_at_period_end && (
          <p style={{ ...mutedStyle, marginTop: "6px" }}>
            Cancels at the end of the paid period{s.next_billing_date ? `, ${formatDate(s.next_billing_date)}` : ""}.
          </p>
        )}
        {s.pending_tier && s.pending_period && (
          <p style={{ ...mutedStyle, marginTop: "6px" }}>
            Changes to {planLabel(s.pending_tier, s.pending_period)} at your next bill{s.next_billing_date ? `, ${formatDate(s.next_billing_date)}` : ""}.
          </p>
        )}

        {onPaidPlan && !stripeBilled && !enterprise && (
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginTop: "14px" }}>
            {pending && (
              <button onClick={undoPending} disabled={busy === "undo"} style={plainButton(busy === "undo")}>
                {busy === "undo" ? "Working…" : "Undo scheduled change"}
              </button>
            )}
            {!s.cancel_at_period_end && (
              <button onClick={() => setConfirm("cancel")} style={dangerButton()}>Cancel plan</button>
            )}
          </div>
        )}

        {s.refund.eligible && s.refund.reason === "remorse_window" && (
          <div style={{ borderTop: "1px solid var(--color-border)", marginTop: "16px", paddingTop: "14px" }}>
            <p style={{ ...mutedStyle, marginBottom: "10px" }}>
              Not what you expected? You can get a full refund of your first payment until {formatDate(s.refund.window_expires_at, { local: true })}.
            </p>
            <button onClick={() => setConfirm("refund")} style={dangerButton()}>Refund first payment</button>
          </div>
        )}
      </div>

      {/* Cancelled for non-payment: restore */}
      {cancelled && latestBill && (
        <div style={{ ...cardStyle, borderColor: "var(--color-critical)" }}>
          <p style={{ fontSize: "14px", fontWeight: 600, marginBottom: "8px" }}>Restore your plan</p>
          <p style={{ ...mutedStyle, marginBottom: "14px" }}>
            Your plan was cancelled because {s.open_bills.length === 1 ? "a bill" : "bills"} went unpaid.
            Pay the open {s.open_bills.length === 1 ? "bill" : "bills"} (
            <span style={monoStyle}>{formatMoney(s.open_bills.reduce((n, b) => n + b.amount_paise, 0), latestBill.currency)}</span>
            ) and the new period of {planLabel(latestBill.tier, latestBill.period)} in one payment, and everything continues as before.
          </p>
          <button
            onClick={() => setPurchase({
              purpose: "restore",
              tier: latestBill.tier,
              period: latestBill.period as Period,
              title: `Restore ${planLabel(latestBill.tier, latestBill.period)}`,
            })}
            style={primaryButton()}
          >
            Restore plan
          </button>
        </div>
      )}

      {/* Open bills */}
      {s.open_bills.length > 0 && !cancelled && !stripeBilled && (
        <div style={cardStyle}>
          <p style={{ fontSize: "14px", fontWeight: 600, marginBottom: "12px" }}>Open {s.open_bills.length === 1 ? "bill" : "bills"}</p>
          {s.open_bills.map(b => (
            <div
              key={b.id}
              style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "16px", flexWrap: "wrap", padding: "10px 0", borderTop: "1px solid var(--color-border)" }}
            >
              <div>
                <p style={{ fontSize: "13px", margin: "0 0 2px" }}>
                  {planLabel(b.tier, b.period)}, {formatDate(b.period_start)} to {formatDate(new Date(Date.parse(`${b.period_end}T00:00:00Z`) - 86400000).toISOString().slice(0, 10))}
                </p>
                <p style={mutedStyle}>
                  Due {formatDate(b.due_date)}. Your plan is cancelled on {formatDate(b.cancel_on)} if it is not paid.
                </p>
                {b.credit_applied_paise > 0 && (
                  <p style={mutedStyle}>
                    Referral credit applied: <span style={monoStyle}>{formatMoney(b.credit_applied_paise, b.currency)}</span>
                  </p>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
                <span style={{ ...monoStyle, fontSize: "15px" }}>{formatMoney(b.amount_paise, b.currency)}</span>
                <button
                  onClick={() => setPurchase({
                    purpose: "bill",
                    billId: b.id,
                    title: `Pay ${planLabel(b.tier, b.period)} bill`,
                  })}
                  style={primaryButton()}
                >
                  Pay now
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Plans */}
      {showPlanCards && (
        <div style={{ marginBottom: "16px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "16px", flexWrap: "wrap", marginBottom: "12px" }}>
            <p style={{ fontSize: "14px", fontWeight: 600, margin: 0 }}>{onPaidPlan ? "Change plan" : "Plans"}</p>
            <div style={{ display: "flex", border: "1px solid var(--color-border)" }}>
              {(["monthly", "annual"] as const).map(p => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  style={{
                    padding: "6px 12px", fontSize: "11px", border: "none", textTransform: "capitalize",
                    background: period === p ? "var(--color-text)" : "transparent",
                    color: period === p ? "var(--color-bg)" : "var(--color-text)",
                    cursor: "pointer",
                  }}
                >
                  {p}{p === "annual" ? " (50% off)" : ""}
                </button>
              ))}
            </div>
          </div>
          {onPaidPlan && (
            <p style={{ ...mutedStyle, marginBottom: "12px" }}>
              Upgrades are charged now. Downgrades start with your next bill. Change the plan or the period, one at a time.
            </p>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-0">
            {PURCHASABLE_TIERS.map((t, i) => {
              const a = cardAction(t);
              const price = displayPrice(t, currency, period);
              const featIdx = PRICING_TIERS.indexOf(t);
              return (
                <div
                  key={t.tier}
                  style={{
                    padding: "24px 20px",
                    border: "1px solid var(--color-border)",
                    borderLeft: i === 0 ? "1px solid var(--color-border)" : "none",
                    background: t.highlight ? "var(--color-surface)" : "var(--color-bg)",
                    display: "flex", flexDirection: "column",
                  }}
                >
                  <p style={{ fontFamily: "var(--font-brand)", fontWeight: 700, fontSize: "18px", margin: "0 0 6px" }}>{t.name}</p>
                  <p style={{ fontFamily: "var(--font-brand)", fontWeight: 700, fontSize: "22px", margin: "0 0 4px" }}>{price.price}</p>
                  {price.note && <p style={{ ...mutedStyle, marginBottom: "4px" }}>{price.note}</p>}
                  <p style={{ ...mutedStyle, marginBottom: "16px" }}>{t.volume}</p>
                  <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: "8px", flex: 1, marginBottom: "20px" }}>
                    {FEATURE_ROWS.map(row => {
                      const value = row.values[featIdx];
                      const included = value !== false;
                      return (
                        <li key={row.label} style={{ fontSize: "12px", color: included ? "var(--color-text-muted)" : "var(--color-border)", display: "flex", gap: "8px" }}>
                          <span style={{ color: included ? "var(--color-text)" : "var(--color-border)", flexShrink: 0 }}>{included ? "+" : "×"}</span>
                          {typeof value === "string" ? value : row.label}
                        </li>
                      );
                    })}
                  </ul>
                  <button
                    onClick={a.onClick}
                    disabled={a.disabled}
                    title={a.hint}
                    style={{
                      padding: "10px 0", fontSize: "13px", fontWeight: 500, width: "100%",
                      border: t.highlight && !a.disabled ? "none" : "1px solid var(--color-border)",
                      background: t.highlight && !a.disabled ? "var(--color-text)" : "transparent",
                      color: t.highlight && !a.disabled ? "var(--color-bg)" : "var(--color-text)",
                      cursor: a.disabled ? "default" : "pointer",
                      opacity: a.disabled ? 0.6 : 1,
                    }}
                  >
                    {a.label}
                  </button>
                </div>
              );
            })}
          </div>
          <p style={{ ...mutedStyle, marginTop: "10px" }}>
            {currency === "INR" ? "Prices exclude GST. " : ""}
            {s.billing_country
              ? `Billed in ${s.billing_currency}.`
              : "Your billing country, chosen at checkout, sets the currency."}
            {" "}Need more?{" "}
            <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>Talk to us about Enterprise</a>.
          </p>
        </div>
      )}

      {/* Payment history */}
      <div style={cardStyle}>
        <p style={{ fontSize: "14px", fontWeight: 600, marginBottom: "12px" }}>Payment history</p>
        {s.payments.length === 0 ? (
          <p style={mutedStyle}>No payments yet.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
                  {["Date", "Description", "Amount", "Status", "Receipt"].map((h, i) => (
                    <th key={h} style={{ padding: "8px 12px 8px 0", textAlign: i === 2 ? "right" : "left", fontWeight: 500, color: "var(--color-text-muted)" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {s.payments.map(p => (
                  <tr key={p.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                    <td style={{ padding: "10px 12px 10px 0", whiteSpace: "nowrap" }}>{formatDate(p.captured_at ?? p.created_at, { local: true })}</td>
                    <td style={{ padding: "10px 12px 10px 0" }}>{p.description ?? p.purpose}</td>
                    <td style={{ padding: "10px 12px 10px 0", textAlign: "right", ...monoStyle }}>{formatMoney(p.amount_paise, p.currency)}</td>
                    <td style={{ padding: "10px 12px 10px 0", color: p.status === "failed" ? "var(--color-critical)" : undefined }}>{statusWord(p.status)}</td>
                    <td style={{ padding: "10px 0" }}>
                      {p.status === "captured" || p.status === "refunded"
                        ? <Link href={`/billing/receipt/${p.id}`} style={{ color: "var(--color-text)" }}>View</Link>
                        : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Billing details */}
      {!stripeBilled && (
        <form onSubmit={saveDetails} style={cardStyle}>
          <p style={{ fontSize: "14px", fontWeight: 600, marginBottom: "4px" }}>Billing details</p>
          <p style={{ ...mutedStyle, marginBottom: "16px" }}>
            Printed on your receipts. Past receipts keep the details they were issued with.
            {currency === "INR" ? " GST tax invoices will be available later." : ""}
          </p>
          <div style={{ display: "grid", gap: "14px", maxWidth: "520px" }}>
            <div>
              <p style={labelStyle}>Legal name</p>
              <input value={legalName} onChange={e => setLegalName(e.target.value)} maxLength={255} placeholder="Your company's registered name" style={inputStyle} />
            </div>
            <div>
              <p style={labelStyle}>Address</p>
              <textarea value={address} onChange={e => setAddress(e.target.value)} maxLength={1000} rows={3} style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }} />
            </div>
            <div>
              <p style={labelStyle}>Billing country</p>
              {s.billing_country ? (
                <p style={{ fontSize: "13px", margin: 0 }}>
                  {countryName(s.billing_country)}
                  <span style={{ color: "var(--color-text-muted)" }}>{`, billed in ${s.billing_currency}. Contact support to change it.`}</span>
                </p>
              ) : (
                <>
                  <select value={country} onChange={e => setCountry(e.target.value)} style={inputStyle}>
                    <option value="">Not set yet</option>
                    {COUNTRIES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
                  </select>
                  <p style={{ ...mutedStyle, marginTop: "6px" }}>
                    Your billing country sets your currency. Contact{" "}
                    <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>support@clewsec.com</a>{" "}
                    to change it later.
                  </p>
                </>
              )}
            </div>
            {s.billing_currency === "INR" && s.billing_country && (
              <div>
                <p style={labelStyle}>GSTIN (optional)</p>
                <input value={gstin} onChange={e => setGstin(e.target.value)} placeholder="22AAAAA0000A1Z5" style={{ ...inputStyle, ...monoStyle }} />
              </div>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "16px" }}>
            <button type="submit" disabled={savingDetails} style={primaryButton(savingDetails)}>
              {savingDetails ? "Saving…" : "Save details"}
            </button>
            {detailsMsg && (
              <span style={{ fontSize: "12px", color: detailsMsg.ok ? "var(--color-low)" : "var(--color-critical)" }}>{detailsMsg.text}</span>
            )}
          </div>
        </form>
      )}

      {purchase && (
        <PurchaseDialog
          target={purchase}
          lockedCountry={s.billing_country}
          savedGstin={s.billing_details.gstin}
          blockingTosAccepted={blockingTosAccepted}
          trialActive={pilot}
          onClose={() => setPurchase(null)}
          onPaid={async () => {
            setPurchase(null);
            setNotice({ ok: true, text: "Payment received. Your plan is up to date." });
            await refreshAll();
          }}
        />
      )}

      {confirm && confirmText && (
        <Confirm
          title={confirmText.title}
          body={confirmText.body}
          confirmLabel={confirmText.label}
          cancelLabel={confirmText.cancel}
          danger={confirmText.danger}
          busy={busy === "confirm"}
          onConfirm={runConfirmed}
          onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  );
}
