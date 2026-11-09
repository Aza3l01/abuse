import type { Metadata } from "next";
import Link from "next/link";
import { LegalLayout, legalH2Style, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Subscription Agreement",
  description: "Subscription Agreement for Clew, Basic, Growth, and Pro plans.",
};

export default function SubscriptionAgreementPage() {
  return (
    <LegalLayout title="Subscription Agreement" lastUpdated="November 9, 2026">
      <p style={legalPStyle}>
        This Subscription Agreement applies to the Basic, Growth and Pro
        plans and sits alongside the{" "}
        <Link href="/legal/terms" style={{ color: "var(--color-text)" }}>Terms of Service</Link>.
        If the two differ on a subject covered here, this agreement prevails
        for the paid plans. The free Starter plan has no blocking and no
        subscription, and is not covered by this agreement.
      </p>

      <h2 style={legalH2Style}>Plans and usage</h2>
      <p style={legalPStyle}>
        Each plan has a monthly volume of analysed log records, a retention
        window for detection data and a set of features, as shown on the
        pricing page and in the product. When your volume is reached,
        scanning pauses as described in section 1 of the Terms of Service.
        There is no overage billing. You may upgrade at any time to a plan
        with a higher volume.
      </p>

      <h2 style={legalH2Style}>Access to your S3 bucket</h2>
      <p style={legalPStyle}>
        You grant Clew read-only access to the S3 bucket and prefix you
        configure, through access that you create (such as an IAM role) and
        can revoke at any time. Clew reads log objects in that location only to analyse them,
        does not write to or delete from your bucket, and stops reading as
        as soon as you revoke the access or disconnect the bucket.
      </p>

      <h2 style={legalH2Style}>Blocking consent</h2>
      <p style={legalPStyle}>
        Where your plan includes blocking and you configure an AWS WAF or
        Cloudflare integration, you authorise Clew to add IP addresses to,
        and remove them from, the IP set or firewall rules you designated,
        using the credentials you supply. Manual blocking acts only when you
        ask for it. Automatic blocking, on plans that include it, acts on
        Clew&apos;s own detection and the thresholds you set. Detection is
        probabilistic, so a legitimate address can be blocked in error. You
        remain responsible for your own firewall configuration and for
        keeping any addresses that must never be blocked on your own
        allowlist. You can unblock any address, and switch automatic
        blocking off, at any time. If your plan is lowered or ends, addresses
        already blocked stay blocked until you unblock them.
      </p>

      <h2 style={legalH2Style}>Warranty and liability</h2>
      <p style={legalPStyle}>
        The service is provided on an &quot;as is&quot; basis. Clew does not
        warrant that it will detect every abusive request, that it will be
        uninterrupted or error free, or that blocking will not affect
        legitimate traffic. To the maximum extent permitted by law, Clew is
        not liable for indirect or consequential loss, loss of revenue or
        loss of data, and its total liability arising from this agreement
        is limited to the amount you paid for the service in the 12 months
        before the claim. Nothing in this agreement limits liability that
        cannot be limited under applicable law.
      </p>

      <h2 style={legalH2Style}>Term and ending the agreement</h2>
      <p style={legalPStyle}>
        The agreement runs for as long as you hold a paid plan. You can
        cancel at any time, and the plan then ends at the end of the period
        you have already paid for. Clew may suspend or end an account that
        breaks the acceptable use rules in the Terms of Service or that
        uses the service unlawfully. Ending the agreement does not remove
        amounts already due. On account deletion, data is handled as
        described in the{" "}
        <Link href="/legal/privacy" style={{ color: "var(--color-text)" }}>Privacy Policy</Link>.
      </p>

      <h2 style={legalH2Style}>Billing terms</h2>
      <p style={legalPStyle}>
        Paid plans are billed first and paid after, with no autopay. A bill
        is issued on the 1st of each billing period and is due on the 20th of
        the same month. If a bill is unpaid, the plan stays active until the
        1st of the following month, then the account moves to the free
        Starter plan. The unpaid bill stays open and payable, and restoring a
        paid plan requires paying all open bills plus the first period of
        the chosen plan in one checkout.
      </p>
      <p style={legalPStyle}>
        Upgrades take effect immediately and are paid at the time of the
        upgrade, once every open bill has been paid. Moving to an annual plan
        costs the full annual price, and the time left on the previous plan
        is forfeited. Downgrades take effect from your next bill. Cancelling
        takes effect at the end of the period you have already paid for.
        Prices for customers billed in INR exclude GST. The full wording is
        in section 4 of the{" "}
        <Link href="/legal/terms" style={{ color: "var(--color-text)" }}>Terms of Service</Link>{" "}
        and in the{" "}
        <Link href="/legal/refund-policy" style={{ color: "var(--color-text)" }}>Refund Policy</Link>.
      </p>

      <h2 style={legalH2Style}>Legal entity</h2>
      <p style={legalPStyle}>
        This agreement is issued by Clew Technologies Private Limited (CIN
        U62090KL2026PTC104122), a private limited company incorporated in
        India. It is governed by the laws of India, and the courts at
        Idukki, Kerala have exclusive jurisdiction over any dispute arising
        from it.
      </p>
    </LegalLayout>
  );
}
