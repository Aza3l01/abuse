"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { apiFetch } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/billing";
import { DASHBOARD_URL } from "@/lib/urls";

interface ReferralCredit {
  id: string;
  status: "pending" | "available" | "applied" | "revoked";
  amount_paise: number;
  currency: string;
  earned_at: string | null;
  vests_at: string | null;
  releases_at: string | null;
  applied_at: string | null;
}

interface ReferralStatus {
  referral_code: string | null;
  credit_pct: number;
  is_referred: boolean;
  referred_state: "waiting_for_first_payment" | "waiting_for_first_bill" | "applied" | null;
  free_bill_paise: number | null;
  free_bill_currency: string | null;
  plan_monthly_paise: number | null;
  plan_currency: string | null;
  signups: number;
  paying: number;
  totals: Record<string, { pending: number; available: number; applied: number }>;
  credits: ReferralCredit[];
}

const labelStyle: CSSProperties = {
  fontSize: "11px",
  color: "var(--color-text-muted)",
  textTransform: "uppercase",
  letterSpacing: "0.07em",
  marginBottom: "8px",
};
const mutedStyle: CSSProperties = { fontSize: "12px", color: "var(--color-text-muted)", margin: 0 };
const cellStyle: CSSProperties = { padding: "8px 12px 8px 0", borderBottom: "1px solid var(--color-border)", fontSize: "13px" };
const monoStyle: CSSProperties = { fontFamily: "var(--font-mono)" };

const STATUS_LABEL: Record<ReferralCredit["status"], string> = {
  pending: "Pending",
  available: "Available",
  applied: "Used on a bill",
  revoked: "Cancelled",
};

function referredLine(status: ReferralStatus): string | null {
  if (!status.is_referred) return null;
  switch (status.referred_state) {
    case "applied":
      return "Your organisation was referred. One month of your second bill was free.";
    case "waiting_for_first_bill":
      return "Your organisation was referred. One month of your second bill is free: it is taken off on your next bill date.";
    default:
      return "Your organisation was referred. One month of your second bill is free once you start a paid plan.";
  }
}

/** Neutral share bar: used, available and pending as shares of everything earned. */
function CreditBar({ totals, currency }: { totals: { pending: number; available: number; applied: number }; currency: string }) {
  const total = totals.applied + totals.available + totals.pending;
  if (total <= 0) return null;
  const segments = [
    { key: "applied", label: "Used", value: totals.applied, background: "var(--color-text-muted)" },
    { key: "available", label: "Available", value: totals.available, background: "var(--color-text)" },
    { key: "pending", label: "Pending", value: totals.pending, background: "var(--color-surface)" },
  ];
  return (
    <div style={{ marginBottom: "12px" }}>
      <div
        role="img"
        aria-label={segments.map((s) => `${s.label} ${formatMoney(s.value, currency)}`).join(", ")}
        style={{ display: "flex", height: "10px", border: "1px solid var(--color-border)", borderRadius: 0, overflow: "hidden" }}
      >
        {segments.map((s) =>
          s.value > 0 ? <div key={s.key} style={{ width: `${(s.value / total) * 100}%`, background: s.background }} /> : null,
        )}
      </div>
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", marginTop: "6px" }}>
        {segments.map((s) => (
          <span key={s.key} style={{ ...mutedStyle, ...monoStyle }}>
            {s.label} {formatMoney(s.value, currency)}
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * Phase 12: referrals on a credit ledger. Shows this org's own invite link,
 * how many organisations signed up and paid, and the credits earned (pending
 * for 72 hours after the referred organisation's first payment, then
 * available, then used on a bill). Credit is never paid out as cash and never
 * discounts a charge directly: it comes off the org's own next bills.
 * Owner-only, like GET /billing/referral-status. Read live on every load,
 * never cached.
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
    ? `${DASHBOARD_URL}/register?ref=${encodeURIComponent(status.referral_code)}`
    : null;
  const currencies = Object.keys(status.totals);
  const referred = referredLine(status);

  function copyLink() {
    if (!inviteLink) return;
    navigator.clipboard.writeText(inviteLink).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div style={{ border: "1px solid var(--color-border)", padding: "20px", background: "var(--color-bg)" }}>
      {referred && <p style={{ ...mutedStyle, marginBottom: "16px" }}>{referred}</p>}

      <p style={{ fontSize: "13px", margin: "0 0 4px" }}>
        Share your invite link. They get one month free on their second bill. Once their first payment is 72 hours old
        with no refund, you get a credit worth their first payment, up to one year of your own plan, taken off your
        next bills.
      </p>
      <p style={{ ...mutedStyle, marginBottom: "20px" }}>
        Credit is never paid out as cash. If the referred organisation is refunded within 72 hours, your credit is
        cancelled.
      </p>

      {inviteLink && (
        <div style={{ marginBottom: "20px" }}>
          <p style={labelStyle}>Your invite link</p>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <input
              readOnly
              value={inviteLink}
              onFocus={(e) => e.target.select()}
              aria-label="Your invite link"
              style={{
                flex: 1,
                minWidth: "220px",
                padding: "7px 10px",
                fontSize: "12px",
                fontFamily: "var(--font-mono)",
                border: "1px solid var(--color-border)",
                background: "var(--color-surface)",
                color: "var(--color-text)",
                borderRadius: 0,
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
                borderRadius: 0,
              }}
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: "32px", flexWrap: "wrap", marginBottom: "20px" }}>
        <div>
          <p style={labelStyle}>Signed up</p>
          <p style={{ ...monoStyle, fontSize: "18px", margin: 0 }}>{status.signups}</p>
        </div>
        <div>
          <p style={labelStyle}>Paying</p>
          <p style={{ ...monoStyle, fontSize: "18px", margin: 0 }}>{status.paying}</p>
        </div>
      </div>

      {currencies.length > 0 && (
        <div style={{ marginBottom: "20px" }}>
          <p style={labelStyle}>Credit</p>
          {currencies.map((c) => (
            <div key={c}>
              <CreditBar totals={status.totals[c]} currency={c} />
              {status.plan_monthly_paise && status.plan_currency === c && status.totals[c].available > 0 && (
                <p style={{ ...mutedStyle, marginBottom: "12px" }}>
                  Available credit covers about{" "}
                  {Math.floor((status.totals[c].available / status.plan_monthly_paise) * 10) / 10} months of your plan.
                </p>
              )}
            </div>
          ))}
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr>
                {["Currency", "Pending", "Available", "Used"].map((h) => (
                  <th key={h} style={{ ...cellStyle, ...mutedStyle, textAlign: "left", fontWeight: 500 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {currencies.map((c) => (
                <tr key={c}>
                  <td style={{ ...cellStyle, ...monoStyle }}>{c}</td>
                  <td style={{ ...cellStyle, ...monoStyle }}>{formatMoney(status.totals[c].pending, c)}</td>
                  <td style={{ ...cellStyle, ...monoStyle }}>{formatMoney(status.totals[c].available, c)}</td>
                  <td style={{ ...cellStyle, ...monoStyle }}>{formatMoney(status.totals[c].applied, c)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ ...mutedStyle, marginTop: "8px" }}>
            Pending credit becomes available 72 hours after the first payment of the referred organisation, if it is not
            refunded. The daily billing run releases it, so allow up to a day more.
          </p>
        </div>
      )}

      {status.credits.length > 0 && (
        <div>
          <p style={labelStyle}>History</p>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr>
                {["Earned", "Amount", "Status"].map((h) => (
                  <th key={h} style={{ ...cellStyle, ...mutedStyle, textAlign: "left", fontWeight: 500 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {status.credits.map((c) => (
                <tr key={c.id}>
                  <td style={{ ...cellStyle, ...monoStyle }}>{formatDate(c.earned_at)}</td>
                  <td style={{ ...cellStyle, ...monoStyle }}>{formatMoney(c.amount_paise, c.currency)}</td>
                  <td style={cellStyle}>
                    {STATUS_LABEL[c.status]}
                    {c.status === "pending" && c.releases_at && (
                      <span style={{ ...mutedStyle, marginLeft: "8px" }}>from {formatDate(c.releases_at)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
