import type { Metadata } from "next";
import { LegalLayout, legalH2Style, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Refund Policy",
  description: "Refund Policy for Clew subscriptions.",
};

export default function RefundPolicyPage() {
  return (
    <LegalLayout title="Refund Policy" lastUpdated="October 1, 2026">
      <h2 style={legalH2Style}>1. Cancelling before your first charge</h2>
      <p style={legalPStyle}>
        If you were onboarded with a promotional Growth trial, you can
        cancel it at any time before it would convert to a paid subscription
        at no cost: your account simply reverts to the free Starter plan.
        No charge occurs, so there is nothing to refund.
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

      <h2 style={legalH2Style}>4. Annual billing</h2>
      <p style={legalPStyle}>
        Annual plans are billed once, upfront, for the full year at a 50%
        discount against the monthly price. The 72-hour remorse window in
        Section 2 applies in exactly the same way to an annual charge as it
        does to a monthly one: if your first payment on the account is an
        annual charge, you can request a full refund within 72 hours of that
        charge. Outside that window, an annual charge is non-refundable for
        the remainder of the year, including if you stop using the service or
        cancel partway through, consistent with Section 3. Your access
        continues for the full year you already paid for.
      </p>

      <h2 style={legalH2Style}>5. How to cancel</h2>
      <p style={legalPStyle}>
        Cancel any time from your account settings, or by emailing{" "}
        <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>support@clewsec.com</a>.
      </p>

      <h2 style={legalH2Style}>6. Legal entity</h2>
      <p style={legalPStyle}>
        This policy is issued by Clew Technologies Private Limited (CIN
        U62090KL2026PTC104122), a private limited company incorporated in
        India. Registered office: Idukki, Kerala, India; the full registered
        address is available on request.
      </p>
    </LegalLayout>
  );
}
