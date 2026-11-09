import type { Metadata } from "next";
import Link from "next/link";
import { LegalLayout, legalH2Style, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "Privacy Policy for Clew: API abuse detection and blocking.",
};

export default function PrivacyPage() {
  return (
    <LegalLayout title="Privacy Policy" lastUpdated="November 9, 2026">
      <p style={legalPStyle}>
        This Privacy Policy describes how Clew (&quot;we&quot;, &quot;us&quot;) collects,
        uses, and protects personal data in connection with the Clew service,
        covered together with our{" "}
        <Link href="/legal/terms" style={{ color: "var(--color-text)" }}>Terms of Service</Link>.
      </p>

      <h2 style={legalH2Style}>1. What we collect</h2>
      <p style={legalPStyle}>
        Account data: name, work email, company name, and password hash.
        Billing data: legal name, billing address and GST number if you
        provide them, and a record of each bill and payment (amount, date,
        status). Card, UPI and bank details are entered with Razorpay and are
        not stored by Clew. Configuration data: the S3 bucket/prefix you
        connect, AWS region, and
        blocking integration settings. Usage data: the API access logs you
        connect for analysis, which may include IP addresses, request
        methods, endpoints, and user-agents originating from your own
        traffic.
      </p>

      <h2 style={legalH2Style}>2. How we use it</h2>
      <p style={legalPStyle}>
        To operate the detection and blocking service, to communicate about
        your account (verification, security, billing), and to improve the
        product. We do not sell personal data.
      </p>

      <h2 style={legalH2Style}>3. Subprocessors</h2>
      <p style={legalPStyle}>
        We use the following subprocessors to operate the service: Razorpay
        (payment processing; you enter your payment details directly in
        Razorpay Checkout, and Clew sends Razorpay only the amount and an
        internal order reference), Resend (transactional email) and MaxMind
        (IP geolocation lookups for GeoIP-based detection). For Growth-tier
        accounts and above, Groq processes the IP
        address under investigation, aggregated traffic metrics (request rate,
        failure counts, timing patterns), and short indicator strings describing
        the suspicious behaviour (these can include the country, network name
        and endpoint paths involved), in order to generate the plain-language
        threat explanation shown on a verdict&apos;s detail page. Raw request
        bodies and
        other customer log content are not sent to Groq. Our Data Processing
        Agreement describing these in detail is on{" "}
        <Link href="/legal/dpa" style={{ color: "var(--color-text)" }}>our DPA page</Link>.
      </p>

      <h2 style={legalH2Style}>4. Retention</h2>
      <p style={legalPStyle}>
        Log-derived detection data (threat history and IP intelligence) is
        retained on a rolling window that depends on your plan: 7 days on
        Starter, 30 days on Basic, 3 months on Growth, 1 year on Pro, and an
        unlimited window on Enterprise. Data older than your plan&apos;s
        window is permanently deleted on a daily basis, not merely hidden.
        If your plan is lowered because a bill was not paid, your previous
        plan&apos;s window keeps applying for 30 days before the shorter window
        takes effect. If you request account deletion, all associated data
        is permanently deleted within 30 days regardless of plan, except
        payment and billing records (amounts, dates, the organisation name
        and any billing details you saved). Those records are kept for 8
        years from the end of the financial year they relate to, because
        company and tax law in India require us to keep our books of
        account, and are then deleted.
      </p>
      <p style={legalPStyle}>
        Backups are retained for up to 30 days and then permanently deleted.
        Data you delete or that expires from your plan&apos;s retention window can
        therefore remain in a backup for up to 30 more days before it is gone.
      </p>

      <h2 style={legalH2Style}>5. Your rights</h2>
      <p style={legalPStyle}>
        You may access, correct, or request deletion of your personal data at
        any time from your account settings, or by contacting{" "}
        <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>support@clewsec.com</a>.
        This includes rights available under India&apos;s Digital Personal
        Data Protection Act, 2023 and other applicable data protection laws.
        Where Clew acts for you as a processor of your log data, you are
        responsible for the lawful basis for sending that data to us.
        Billing emails (bills, reminders, plan changes) go to the account
        owner by default. The owner can instead send them to selected team
        members marked as billing contacts, or to all members. The plan
        cancellation warning and notice always also go to the owner.
      </p>

      <h2 style={legalH2Style}>6. Security</h2>
      <p style={legalPStyle}>
        Passwords are hashed, sensitive credentials (such as TOTP secrets) are
        encrypted at rest, and access to your S3 bucket is read-only. We
        support optional two-factor authentication on every account.
      </p>

      <h2 style={legalH2Style}>7. Changes</h2>
      <p style={legalPStyle}>
        We may update this Privacy Policy from time to time. Material changes
        will be communicated by email to the address on your account.
      </p>

      <h2 style={legalH2Style}>8. Contact</h2>
      <p style={legalPStyle}>
        Questions about this Privacy Policy can be sent to{" "}
        <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>support@clewsec.com</a>.
        Complaints about how your personal data is handled, and requests to
        exercise your rights, go to the same address with the subject line
        &quot;Privacy grievance&quot;. We acknowledge them within 7 days and
        aim to resolve them within 30 days.
      </p>

      <h2 style={legalH2Style}>9. Data controller</h2>
      <p style={legalPStyle}>
        The data controller for the purposes of this Privacy Policy is Clew
        Technologies Private Limited (CIN U62090KL2026PTC104122), a private
        limited company incorporated in India. Registered office: Idukki,
        Kerala, India; the full registered address is available on request.
      </p>
    </LegalLayout>
  );
}
