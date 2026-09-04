import type { Metadata } from "next";
import { LegalLayout, legalH2Style, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Refund Policy",
  description: "Refund Policy for Clew subscriptions.",
};

export default function RefundPolicyPage() {
  return (
    <LegalLayout title="Refund Policy" lastUpdated="August 10, 2026">
      <h2 style={legalH2Style}>1. Cancelling before your first charge</h2>
      <p style={legalPStyle}>
        You can cancel a trial at any time before it converts to a paid
        subscription at no cost. No charge occurs, so there is nothing to
        refund.
      </p>

      <h2 style={legalH2Style}>2. First payment — 72-hour remorse window</h2>
      <p style={legalPStyle}>
        Within 72 hours of your first payment, you can request a full refund
        for any reason. This is a one-time allowance: it applies only to the
        first charge on an account and is not repeated on any later renewal.
      </p>

      <h2 style={legalH2Style}>3. Everything beyond that</h2>
      <p style={legalPStyle}>
        Outside the 72-hour window on your first payment, and for every
        renewal charge from month two onward regardless of timing, charges
        are non-refundable. This is the same policy most subscription
        software uses: cancelling stops future billing only. Your access
        continues until the end of the billing cycle you already paid for,
        it does not end immediately.
      </p>

      <h2 style={legalH2Style}>4. How to cancel</h2>
      <p style={legalPStyle}>
        Cancel any time from your account settings, or by emailing{" "}
        <a href="mailto:billing@clewsec.com" style={{ color: "var(--color-text)" }}>billing@clewsec.com</a>.
      </p>
    </LegalLayout>
  );
}
