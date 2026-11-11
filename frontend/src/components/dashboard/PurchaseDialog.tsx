"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { SITE_URL } from "@/lib/urls";
import { COUNTRIES, countryName, guessBillingCountry } from "@/lib/countries";
import {
  errorText,
  formatMoney,
  runCheckout,
  type Currency,
  type Period,
  type PurchasePurpose,
  type Quote,
} from "@/lib/billing";

export interface PurchaseTarget {
  purpose: PurchasePurpose;
  title: string;
  tier?: string;
  period?: Period;
  billId?: string;
}

interface Props {
  target: PurchaseTarget;
  /** The org's billing country once set (fixed after the first checkout). */
  lockedCountry: string | null;
  /** GSTIN already on file, used to pre-fill the field. */
  savedGstin: string | null;
  /** The Blocking Subscription Agreement is already accepted for this org. */
  blockingTosAccepted: boolean;
  /** A pilot trial is running, so paying ends it. */
  trialActive: boolean;
  onClose: () => void;
  /** The payment was verified. */
  onPaid: () => void;
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 10px",
  fontSize: "13px",
  border: "1px solid var(--color-border)",
  background: "var(--color-surface)",
  color: "var(--color-text)",
  boxSizing: "border-box",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: "11px",
  color: "var(--color-text-muted)",
  textTransform: "uppercase",
  letterSpacing: "0.07em",
  marginBottom: "6px",
};

const noteStyle: React.CSSProperties = {
  fontSize: "12px",
  color: "var(--color-text-muted)",
  lineHeight: 1.5,
  margin: 0,
};

/**
 * One checkout dialog for every payment: a first plan, an upgrade, an open
 * bill, a restore. The price on screen is a /billing/quote answer computed by
 * the same server code that create-order uses, so the amount shown is the
 * amount charged. The billing country (which fixes the currency) is chosen
 * here for an org that has none yet.
 */
export function PurchaseDialog({
  target,
  lockedCountry,
  savedGstin,
  blockingTosAccepted,
  trialActive,
  onClose,
  onPaid,
}: Props) {
  // Pre-select a guess for an org with no country. The user confirms it, and
  // the confirmed country decides the currency on the server.
  const [country, setCountry] = useState<string>(() => lockedCountry || guessBillingCountry());
  const [gstin, setGstin] = useState(savedGstin ?? "");
  const [tosChecked, setTosChecked] = useState(false);
  const [annualChecked, setAnnualChecked] = useState(false);
  // The last quote answer and the request key it answered. While the current
  // key has no answer yet, a quote is in flight.
  const [outcome, setOutcome] = useState<{ key: string; quote: Quote | null; error: string | null } | null>(null);
  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);

  const isBill = target.purpose === "bill";
  const needsTos = !isBill && !blockingTosAccepted;
  const needsAnnualAck = !isBill && target.period === "annual";
  const needsCountry = !isBill && !lockedCountry;

  const quoteCountry = needsCountry ? country : "";
  const canQuote = !needsCountry || quoteCountry.length === 2;
  const quoteKey = canQuote
    ? JSON.stringify([target.purpose, target.tier, target.period, target.billId, needsCountry, quoteCountry])
    : null;
  const quoting = quoteKey !== null && outcome?.key !== quoteKey;
  const quote: Quote | null = canQuote ? (outcome?.quote ?? null) : null;
  const quoteError: string | null = quoteKey !== null && outcome?.key === quoteKey ? outcome.error : null;

  useEffect(() => {
    if (quoteKey === null) return;
    let cancelled = false;
    apiFetch(`/billing/quote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        purpose: target.purpose,
        tier: target.tier,
        period: target.period,
        bill_id: target.billId,
        billing_country: needsCountry ? quoteCountry : undefined,
      }),
    })
      .then(async (r) => {
        if (!r.ok) {
          const message = await errorText(r, "Could not price this purchase.");
          if (!cancelled) setOutcome({ key: quoteKey, quote: null, error: message });
          return;
        }
        const q: Quote = await r.json();
        if (!cancelled) setOutcome({ key: quoteKey, quote: q, error: null });
      })
      .catch(() => {
        if (!cancelled) {
          setOutcome({ key: quoteKey, quote: null, error: "Could not price this purchase. Check your connection." });
        }
      });
    return () => { cancelled = true; };
  }, [quoteKey, quoteCountry, needsCountry, target.purpose, target.tier, target.period, target.billId]);

  const currency: Currency | null = quote?.currency ?? null;
  const ready =
    quote !== null &&
    !quoting &&
    !paying &&
    (!needsTos || tosChecked) &&
    (!needsAnnualAck || annualChecked);

  async function pay() {
    if (!quote) return;
    setPaying(true);
    setPayError(null);
    const result = await runCheckout(
      {
        purpose: target.purpose,
        tier: target.tier,
        period: target.period,
        bill_id: target.billId,
        accept_blocking_tos: needsTos ? tosChecked : undefined,
        accept_annual_nonrefundable: needsAnnualAck ? annualChecked : undefined,
        gstin: quote.currency === "INR" && gstin.trim() ? gstin.trim() : undefined,
        billing_country: needsCountry ? country : undefined,
      },
      quote.description || target.title,
    );
    setPaying(false);
    if (result.kind === "paid") {
      onPaid();
    } else if (result.kind === "error") {
      setPayError(result.message);
    }
  }

  const buttonLabel = quote ? `Pay ${formatMoney(quote.amount, quote.currency)}` : "Pay";

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(13,13,13,0.6)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
      }}
    >
      <div
        role="dialog"
        aria-label={target.title}
        style={{
          background: "var(--color-bg)", border: "1px solid var(--color-border)",
          padding: "24px", maxWidth: "480px", width: "92%", maxHeight: "90vh", overflowY: "auto",
          animation: "modal-panel-in 150ms ease-out",
        }}
      >
        <p style={{ fontSize: "14px", fontWeight: 600, marginBottom: "16px" }}>{target.title}</p>

        {trialActive && (
          <p style={{ ...noteStyle, marginBottom: "16px" }}>
            Paying ends your trial. Your plan changes to the one you pay for today.
          </p>
        )}

        {/* Billing country */}
        {!isBill && (
          <div style={{ marginBottom: "16px" }}>
            <label style={labelStyle} htmlFor="billing-country">Billing country</label>
            {lockedCountry ? (
              <p style={{ fontSize: "13px", margin: 0 }}>{countryName(lockedCountry)}</p>
            ) : (
              <>
                <select
                  id="billing-country"
                  value={country}
                  onChange={(e) => setCountry(e.target.value)}
                  style={inputStyle}
                >
                  <option value="">Select a country</option>
                  {COUNTRIES.map(([code, name]) => (
                    <option key={code} value={code}>{name}</option>
                  ))}
                </select>
                <p style={{ ...noteStyle, marginTop: "6px" }}>
                  {currency ? `Billed in ${currency}. ` : "Your billing country sets your currency. "}
                  It is fixed once your first payment goes through. After that, contact{" "}
                  <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>support@clewsec.com</a>{" "}
                  to change it.
                </p>
              </>
            )}
          </div>
        )}

        {/* Quote */}
        <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)", padding: "14px 16px", marginBottom: "16px" }}>
          {!canQuote ? (
            <p style={noteStyle}>Select your billing country to see the price.</p>
          ) : quoteError ? (
            <p style={{ fontSize: "12px", color: "var(--color-critical)", margin: 0 }}>{quoteError}</p>
          ) : quote ? (
            <>
              <p style={{ ...noteStyle, marginBottom: "4px" }}>{quote.description}</p>
              <p style={{ fontSize: "20px", fontWeight: 600, margin: 0, fontFamily: "var(--font-geist-mono, monospace)" }}>
                {formatMoney(quote.amount, quote.currency)}
              </p>
              {quote.currency === "INR" && (
                <p style={{ ...noteStyle, marginTop: "6px" }}>Prices exclude GST.</p>
              )}
            </>
          ) : (
            <p style={noteStyle}>Calculating the price…</p>
          )}
        </div>

        {/* GSTIN, India only */}
        {currency === "INR" && !isBill && (
          <div style={{ marginBottom: "16px" }}>
            <label style={labelStyle} htmlFor="billing-gstin">GSTIN (optional)</label>
            <input
              id="billing-gstin"
              value={gstin}
              onChange={(e) => setGstin(e.target.value)}
              placeholder="22AAAAA0000A1Z5"
              style={{ ...inputStyle, fontFamily: "var(--font-geist-mono, monospace)" }}
            />
            <p style={{ ...noteStyle, marginTop: "6px" }}>
              Printed on your receipt. GST tax invoices will be available later.
            </p>
          </div>
        )}

        {target.purpose === "upgrade" && target.period === "annual" && (
          <p style={{ ...noteStyle, marginBottom: "14px" }}>
            An annual plan is charged at its full price and a new year starts now. Any time left on your
            current plan is forfeited and nothing is credited.
          </p>
        )}

        {/* Annual acknowledgement */}
        {needsAnnualAck && (
          <label style={{ display: "flex", gap: "10px", alignItems: "flex-start", marginBottom: "14px", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={annualChecked}
              onChange={(e) => setAnnualChecked(e.target.checked)}
              style={{ marginTop: "3px" }}
            />
            <span style={{ fontSize: "12px", lineHeight: 1.5 }}>
              I understand this annual charge is non-refundable after 72 hours.
            </span>
          </label>
        )}

        {/* Blocking agreement */}
        {needsTos && (
          <label style={{ display: "flex", gap: "10px", alignItems: "flex-start", marginBottom: "14px", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={tosChecked}
              onChange={(e) => setTosChecked(e.target.checked)}
              style={{ marginTop: "3px" }}
            />
            <span style={{ fontSize: "12px", lineHeight: 1.5 }}>
              This plan includes IP blocking. Clew adds malicious IPs to your AWS WAF and Cloudflare account
              when you block them. I accept the{" "}
              <a
                href={`${SITE_URL}/legal/subscription-agreement`}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "var(--color-text)" }}
              >
                Blocking Subscription Agreement ↗
              </a>.
            </span>
          </label>
        )}

        {currency && (
          <p style={{ ...noteStyle, marginBottom: "16px" }}>
            {currency === "INR"
              ? "Pay with UPI, card, netbanking or wallet."
              : "Pay with credit or debit card."}
          </p>
        )}

        {payError && (
          <p style={{ fontSize: "12px", color: "var(--color-critical)", marginBottom: "14px", lineHeight: 1.5 }}>{payError}</p>
        )}

        <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
          <button
            onClick={onClose}
            disabled={paying}
            style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: paying ? "default" : "pointer" }}
          >
            Cancel
          </button>
          <button
            onClick={pay}
            disabled={!ready}
            style={{
              padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-text)",
              background: "var(--color-text)", color: "var(--color-bg)",
              cursor: ready ? "pointer" : "default", opacity: ready ? 1 : 0.5,
            }}
          >
            {paying ? "Working…" : buttonLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
