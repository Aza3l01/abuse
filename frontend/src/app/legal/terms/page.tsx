import type { Metadata } from "next";
import Link from "next/link";
import { LegalLayout, legalH2Style, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "Terms of Service for Clew — API abuse detection and blocking.",
};

export default function TermsPage() {
  return (
    <LegalLayout title="Terms of Service" lastUpdated="August 10, 2026">
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
        No payment method is required to start a Growth trial. If a Growth
        trial ends without an active paid subscription, the account reverts
        to the free Starter plan: scanning and dashboard access continue
        without interruption, only Growth&apos;s additional features
        (automatic blocking, extended retention, higher call volume) are
        unavailable until you subscribe.
      </p>

      <h2 style={legalH2Style}>4. Refunds and cancellations</h2>
      <p style={legalPStyle}>
        You can request a full refund within 72 hours of your first paid
        charge. After that window, and on any renewal charge, payments are
        non-refundable. Cancelling stops future billing only: your plan
        stays active until the end of the billing period you already paid
        for. See the full{" "}
        <Link href="/legal/refund-policy" style={{ color: "var(--color-text)" }}>
          Refund Policy
        </Link>{" "}for details.
      </p>

      <h2 style={legalH2Style}>5. Customer data</h2>
      <p style={legalPStyle}>
        You retain all rights to the log data you connect to Clew. We access
        it only to provide the service (detection, blocking, and reporting)
        and as described in our Privacy Policy. Clew&apos;s access to your S3
        bucket is read-only.
      </p>

      <h2 style={legalH2Style}>6. Acceptable use</h2>
      <p style={legalPStyle}>
        You may not use Clew to monitor or block traffic you do not have the
        legal right to process, or in a manner that violates applicable law.
      </p>

      <h2 style={legalH2Style}>7. Account deletion</h2>
      <p style={legalPStyle}>
        You may request deletion of your account at any time from your
        account settings. Your data will be permanently deleted within 30
        days of your request.
      </p>

      <h2 style={legalH2Style}>8. Disclaimers and liability</h2>
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

      <h2 style={legalH2Style}>9. Changes</h2>
      <p style={legalPStyle}>
        We may update these Terms from time to time. Material changes will be
        communicated by email to the address on your account.
      </p>

      <h2 style={legalH2Style}>10. Legal entity and governing law</h2>
      <p style={legalPStyle}>
        Clew is operated by Clew Technologies Private Limited (CIN
        U62090KL2026PTC104122), a private limited company incorporated in
        India. Registered office: Idukki, Kerala, India; the full registered
        address is available on request. These Terms are governed by the
        laws of India, and the courts at Idukki, Kerala have exclusive
        jurisdiction over any dispute arising from them.
      </p>

      <h2 style={legalH2Style}>11. Contact</h2>
      <p style={legalPStyle}>
        Questions about these Terms can be sent to{" "}
        <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>support@clewsec.com</a>.
      </p>
    </LegalLayout>
  );
}
