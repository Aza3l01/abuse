"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { countryName } from "@/lib/countries";
import { errorText, formatDate, formatMoney, type Currency } from "@/lib/billing";

interface Receipt {
  id: string;
  razorpay_payment_id: string | null;
  status: string;
  purpose: string;
  currency: Currency;
  amount_paise: number;
  created_at: string | null;
  captured_at: string | null;
  refunded_at: string | null;
  lines: { description: string; amount_paise: number }[];
  customer_name: string;
  customer_address: string | null;
  customer_gstin: string | null;
  customer_country: string | null;
}

const labelStyle: React.CSSProperties = {
  fontSize: "11px",
  color: "var(--color-text-muted)",
  textTransform: "uppercase",
  letterSpacing: "0.07em",
  margin: "0 0 4px",
};

const monoStyle: React.CSSProperties = { fontFamily: "var(--font-geist-mono, monospace)", fontSize: "12px" };

/**
 * Printable payment receipt. A receipt, not a tax invoice: no tax lines. The
 * customer details are the values stored with the payment when it was made.
 * The print rule hides the dashboard chrome so only the receipt prints.
 */
export default function ReceiptPage() {
  const params = useParams<{ id: string }>();
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!params?.id) return;
    apiFetch(`/billing/payments/${encodeURIComponent(params.id)}`)
      .then(async (r) => {
        if (!r.ok) {
          setError(r.status === 403
            ? "Only the organisation owner can view receipts."
            : await errorText(r, "Could not load this receipt."));
          return;
        }
        setReceipt(await r.json());
      })
      .catch(() => setError("Could not load this receipt."));
  }, [params?.id]);

  return (
    <div style={{ padding: "32px", maxWidth: "720px" }}>
      <style>{`
        @media print {
          body * { visibility: hidden; }
          .receipt-print, .receipt-print * { visibility: visible; }
          .receipt-print { position: absolute; left: 0; top: 0; width: 100%; border: none !important; }
          .receipt-noprint { display: none !important; }
        }
      `}</style>

      <div className="receipt-noprint" style={{ display: "flex", justifyContent: "space-between", marginBottom: "20px" }}>
        <Link href="/settings#billing" style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>← Billing</Link>
        {receipt && (
          <button
            onClick={() => window.print()}
            style={{ padding: "6px 14px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
          >
            Print
          </button>
        )}
      </div>

      {error && <p style={{ fontSize: "13px", color: "var(--color-critical)" }}>{error}</p>}
      {!error && !receipt && <p style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>Loading…</p>}

      {receipt && (
        <div className="receipt-print" style={{ border: "1px solid var(--color-border)", background: "var(--color-bg)", padding: "32px" }}>
          <p style={{ fontSize: "16px", fontWeight: 600, margin: "0 0 2px" }}>Clew Technologies Private Limited</p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "0 0 28px" }}>Payment receipt</p>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px", marginBottom: "28px" }}>
            <div>
              <p style={labelStyle}>Receipt</p>
              <p style={{ ...monoStyle, margin: 0, wordBreak: "break-all" }}>{receipt.id}</p>
            </div>
            <div>
              <p style={labelStyle}>Razorpay payment</p>
              <p style={{ ...monoStyle, margin: 0, wordBreak: "break-all" }}>{receipt.razorpay_payment_id ?? "—"}</p>
            </div>
            <div>
              <p style={labelStyle}>Date</p>
              <p style={{ fontSize: "13px", margin: 0 }}>{formatDate(receipt.captured_at ?? receipt.created_at, { local: true })}</p>
            </div>
            <div>
              <p style={labelStyle}>Status</p>
              <p style={{ fontSize: "13px", margin: 0 }}>
                {receipt.status === "refunded"
                  ? `Refunded on ${formatDate(receipt.refunded_at, { local: true })}`
                  : "Paid"}
              </p>
            </div>
          </div>

          <div style={{ marginBottom: "28px" }}>
            <p style={labelStyle}>Billed to</p>
            <p style={{ fontSize: "13px", margin: "0 0 2px" }}>{receipt.customer_name}</p>
            {receipt.customer_address && (
              <p style={{ fontSize: "13px", margin: "0 0 2px", whiteSpace: "pre-line" }}>{receipt.customer_address}</p>
            )}
            {receipt.customer_country && (
              <p style={{ fontSize: "13px", margin: "0 0 2px" }}>{countryName(receipt.customer_country)}</p>
            )}
            {receipt.customer_gstin && (
              <p style={{ ...monoStyle, margin: 0 }}>GSTIN {receipt.customer_gstin}</p>
            )}
          </div>

          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", marginBottom: "8px" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
                <th style={{ textAlign: "left", fontWeight: 500, color: "var(--color-text-muted)", padding: "8px 0" }}>Description</th>
                <th style={{ textAlign: "right", fontWeight: 500, color: "var(--color-text-muted)", padding: "8px 0" }}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {receipt.lines.map((l, i) => (
                <tr key={i} style={{ borderBottom: "1px solid var(--color-border)" }}>
                  <td style={{ padding: "10px 0" }}>{l.description}</td>
                  <td style={{ padding: "10px 0", textAlign: "right", ...monoStyle }}>{formatMoney(l.amount_paise, receipt.currency)}</td>
                </tr>
              ))}
              <tr>
                <td style={{ padding: "12px 0", fontWeight: 600 }}>Total ({receipt.currency})</td>
                <td style={{ padding: "12px 0", textAlign: "right", fontWeight: 600, ...monoStyle }}>
                  {formatMoney(receipt.amount_paise, receipt.currency)}
                </td>
              </tr>
            </tbody>
          </table>

          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", lineHeight: 1.5, margin: "20px 0 0" }}>
            This is a payment receipt, not a tax invoice.
            {receipt.currency === "INR" && " GST tax invoices will be available later."}
          </p>
        </div>
      )}
    </div>
  );
}
