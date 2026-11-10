import type { Metadata } from "next";
import { LegalLayout, legalH2Style, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Refund Policy",
  description: "Refund Policy for Clew subscriptions.",
};

export default function RefundPolicyPage() {
  return (
    <LegalLayout title="Refund Policy" lastUpdated="November 9, 2026">
      <h2 style={legalH2Style}>1. Cancelling before your first charge</h2>
      <p style={legalPStyle}>
        A promotional Growth trial is free and is never charged
        automatically. If you do not choose a paid plan, your account
        simply reverts to the free Starter plan when the trial ends. No
        charge occurs, so there is nothing to refund.
      </p>

      <h2 style={legalH2Style}>2. First payment (72-hour remorse window)</h2>
      <p style={legalPStyle}>
        You can request a full refund for any reason within 72 hours of the
        first payment ever captured on your account. This is a one-time
        allowance: it runs from that first payment only and is not repeated
        on any later bill. Any other payment captured inside the same 72
        hours (for example an upgrade) is refunded with it. A refund returns
        the amount to the original payment method through Razorpay, and your
        account moves to the free Starter plan.
      </p>

      <h2 style={legalH2Style}>3. Everything beyond that</h2>
      <p style={legalPStyle}>
        Outside the 72-hour window on your first payment, and for every
        later bill regardless of timing, charges are non-refundable.
        Cancelling stops future billing only. Your access continues until
        the end of the period you already paid for, it does not end
        immediately. A bill you did not pay is not a charge, so there is
        nothing to refund; it stays open and payable.
      </p>
      <p style={legalPStyle}>
        Referral credits are never paid out in cash and are never refunded.
        If you referred another customer and that customer is refunded
        before your credit becomes available, your credit is cancelled.
      </p>

      <h2 style={legalH2Style}>4. Annual billing</h2>
      <p style={legalPStyle}>
        Annual plans are billed once, upfront, for the full year at a 50%
        discount against the monthly price. The 72-hour remorse window in
        Section 2 applies in exactly the same way to an annual charge as it
        does to a monthly one: if the first payment on the account is an
        annual charge, you can request a full refund within 72 hours of that
        payment. Outside that window, an annual charge is non-refundable for
        the remainder of the year, including if you stop using the service or
        cancel partway through, consistent with Section 3. You acknowledge
        this at checkout, and your access continues for the full year you
        already paid for.
      </p>
      <p style={legalPStyle}>
        If you upgrade to an annual plan, from monthly or from a lower annual
        plan, the full annual price is charged, a new year starts on the day
        you pay, and the time left on your previous plan is forfeited. It is
        not credited and not refunded.
      </p>

      <h2 style={legalH2Style}>5. How to cancel or request a refund</h2>
      <p style={legalPStyle}>
        Account owners can cancel, and request a refund while the 72-hour
        window is open, from Settings, or by emailing{" "}
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
