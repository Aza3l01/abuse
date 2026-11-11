import type { Metadata } from "next";
import Link from "next/link";
import { LegalLayout, legalH2Style, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "Terms of Service for Clew: API abuse detection and blocking.",
};

export default function TermsPage() {
  return (
    <LegalLayout title="Terms of Service" lastUpdated="November 9, 2026">
      <p style={legalPStyle}>
        These Terms of Service (&quot;Terms&quot;) govern access to and use of Clew
        (&quot;Clew&quot;, &quot;we&quot;, &quot;us&quot;), a service that ingests API access
        log data to detect and, where configured, block abusive traffic. By
        creating an account you agree to these Terms and to our{" "}
        <Link href="/legal/privacy" style={{ color: "var(--color-text)" }}>Privacy Policy</Link>.
      </p>

      <h2 style={legalH2Style}>1. The service</h2>
      <p style={legalPStyle}>
        Clew reads access log data from a customer-configured, read-only Amazon
        S3 location (API Gateway or Application Load Balancer log format) and
        analyses it to detect abusive request patterns. Depending on the
        subscribed plan and configuration, Clew may optionally take blocking
        action via AWS WAF IP sets or Cloudflare firewall rules.
      </p>
      <p style={legalPStyle}>
        Each plan includes a monthly volume of analysed log records. When your
        account reaches that volume, scanning pauses: log files that arrive
        after that point are not analysed, now or later. There is no overage
        charge, and the limit cannot be extended by paying more for the same
        plan. Scanning resumes when the volume counter resets on the 1st of
        the next month (UTC), or as soon as you upgrade to a plan whose volume
        is higher than your usage. We email you at 80% and at 100% of your
        volume. Dashboard access, existing data and IP addresses already
        blocked are not affected by a pause.
      </p>
      <p style={legalPStyle}>
        You can also pause scanning yourself. An owner or admin can pause and
        resume scanning from Settings. While scanning is paused by you, log
        files that arrive are not analysed, and when you resume, the logs
        written during the pause are skipped, now and later. Saved verdicts,
        blocking rules, alerts for earlier findings, your account and billing
        are not affected by a pause.
      </p>

      <h2 style={legalH2Style}>2. Accounts</h2>
      <p style={legalPStyle}>
        You must provide accurate registration information and are responsible
        for safeguarding your account credentials, including any multi-factor
        authentication recovery codes. Notify us immediately of any
        unauthorised use of your account.
      </p>

      <h2 style={legalH2Style}>3. Trials and subscriptions</h2>
      <p style={legalPStyle}>
        New self-serve accounts start immediately on the free Starter plan:
        no trial, no card required, no expiry. Accounts onboarded with a
        promotional code instead receive a 30-day trial of the Growth plan.
        No card or payment is required to start a Growth trial. If a Growth
        trial ends without a paid plan, the account reverts
        to the free Starter plan: scanning and dashboard access continue
        without interruption, only Growth&apos;s additional features
        (automatic blocking, extended retention, higher call volume) are
        unavailable until you choose a plan.
      </p>

      <h2 style={legalH2Style}>4. Billing and payment</h2>
      <p style={legalPStyle}>
        Paid plans are billed first and paid after. Clew does not charge
        your card, UPI or bank account automatically and there is no
        autopay: you pay each bill yourself, online through Razorpay, from
        Settings. Customers billed in India pay in Indian rupees (INR); all
        other customers pay in US dollars (USD).
      </p>
      <p style={legalPStyle}>
        Your first payment is made when you choose a paid plan, and the plan
        starts at once. If you pay on the 1st to the 15th of a month, your
        first bill is issued on the 1st of the next month; if you pay on the
        16th or later, it is issued on the 1st of the month after that.
        Annual plans follow the same rule with 12 months added. After that,
        a bill is issued on the 1st of each billing period and is due on the
        20th of the same month.
      </p>
      <p style={legalPStyle}>
        If a bill is not paid, your plan stays active until the 1st of the
        following month. On that date the account moves to the free Starter
        plan: paid features such as automatic blocking stop, and Starter
        limits apply. Your data keeps your previous plan&apos;s retention
        window for 30 days after the move. The unpaid bill is not cancelled:
        it stays open and payable. IP addresses already blocked stay blocked,
        and you can unblock them at any time.
      </p>
      <p style={legalPStyle}>
        To restore a paid plan after a move to Starter for non-payment, you
        pay all open bills plus the first period of the plan you choose, in
        one checkout. Any new paid purchase requires every open bill to be
        settled first.
      </p>
      <p style={legalPStyle}>
        Upgrades take effect immediately and are paid at the time of the
        upgrade, once every open bill has been paid. Moving to a higher tier
        on the same billing period costs the difference in price, and the
        date of your next bill does not change. Moving from monthly to annual,
        or from one annual plan to a higher annual plan, costs the full price
        of the new annual plan, and a new year starts on the day you pay: the
        monthly time you already paid for, or what remains of your old annual
        plan, is forfeited and nothing is credited or refunded for it.
        Downgrades (to a lower tier, or from annual to monthly) take effect
        from your next bill. We do not prorate. Cancelling takes effect at
        the end of the period you have already paid for, and no further bill
        is issued.
      </p>
      <p style={legalPStyle}>
        Prices for customers billed in INR exclude GST. No GST is collected
        until Clew holds a GST registration; GST tax invoices will be
        available later.
      </p>
      <p style={legalPStyle}>
        Referrals. If you register with another customer&apos;s referral code
        and then make a first payment, one month of the second bill issued to
        you is credited and free; the rest of that bill, if any, stays
        payable. The customer who referred you earns a credit that is pending
        at first and becomes available once your first payment has stood for
        72 hours without being refunded. A referral credit is worth the lower
        of your first payment and the price of a year of the referrer&apos;s
        current plan, in the referrer&apos;s billing currency. A credit only
        reduces your own future bills. It is never
        paid out in cash, cannot be transferred and does not expire. If the
        referred customer is refunded before the credit becomes available,
        the credit is cancelled. We may hold, review or cancel credits that
        we reasonably believe come from fake, self-referred or otherwise
        abusive accounts, and a credit that has been applied to a bill is not
        reversed afterwards.
      </p>

      <h2 style={legalH2Style}>5. Refunds and cancellations</h2>
      <p style={legalPStyle}>
        You can request a full refund within 72 hours of the first payment
        ever captured on your account, whether that payment is monthly or
        annual. After that window, and for every later bill, payments are
        non-refundable. This applies equally to annual plans: an annual
        charge is billed once, upfront, for the full year, and is
        non-refundable after the 72-hour window for the remainder of that
        year. Cancelling stops future billing only: your plan stays active
        until the end of the billing period you already paid for. See the
        full{" "}
        <Link href="/legal/refund-policy" style={{ color: "var(--color-text)" }}>
          Refund Policy
        </Link>{" "}for details.
      </p>

      <h2 style={legalH2Style}>6. Customer data</h2>
      <p style={legalPStyle}>
        You retain all rights to the log data you connect to Clew. We access
        it only to provide the service (detection, blocking, and reporting)
        and as described in our Privacy Policy. Clew&apos;s access to your S3
        bucket is read-only.
      </p>

      <h2 style={legalH2Style}>7. Acceptable use</h2>
      <p style={legalPStyle}>
        You may not use Clew to monitor or block traffic you do not have the
        legal right to process, or in a manner that violates applicable law.
      </p>

      <h2 style={legalH2Style}>8. Account deletion</h2>
      <p style={legalPStyle}>
        You may request deletion of your account at any time from your
        account settings. Your data will be permanently deleted within 30
        days of your request. Payment and billing records (amounts, dates,
        the organisation name, and any billing details you saved) are not
        deleted with the rest of the account. We keep them for 8 years from
        the end of the financial year they relate to, because company and tax
        law in India require us to keep our books of account, and we then
        delete them.
      </p>

      <h2 style={legalH2Style}>9. Disclaimers and liability</h2>
      <p style={legalPStyle}>
        Clew is provided on an &quot;as is&quot; basis. Detection is
        probabilistic and cannot guarantee identification of every abusive
        request or the absence of false positives. To the maximum extent
        permitted by law, Clew&apos;s aggregate liability arising from these
        Terms is limited to the amount paid for the service in the 12 months
        preceding the claim. Plan-specific liability terms are set out in the{" "}
        <Link href="/legal/subscription-agreement" style={{ color: "var(--color-text)" }}>
          Subscription Agreement
        </Link>.
      </p>

      <h2 style={legalH2Style}>10. Changes</h2>
      <p style={legalPStyle}>
        We may update these Terms from time to time. Material changes will be
        communicated by email to the address on your account.
      </p>

      <h2 style={legalH2Style}>11. Legal entity and governing law</h2>
      <p style={legalPStyle}>
        Clew is operated by Clew Technologies Private Limited (CIN
        U62090KL2026PTC104122), a private limited company incorporated in
        India. Registered office: Idukki, Kerala, India; the full registered
        address is available on request. These Terms are governed by the
        laws of India, and the courts at Idukki, Kerala have exclusive
        jurisdiction over any dispute arising from them.
      </p>

      <h2 style={legalH2Style}>12. Contact</h2>
      <p style={legalPStyle}>
        Questions about these Terms can be sent to{" "}
        <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>support@clewsec.com</a>.
      </p>
    </LegalLayout>
  );
}
