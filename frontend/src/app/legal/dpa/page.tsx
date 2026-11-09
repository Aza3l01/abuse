import type { Metadata } from "next";
import Link from "next/link";
import { LegalLayout, legalH2Style, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Data Processing Agreement",
  description: "Data Processing Agreement for Clew.",
};

export default function DpaPage() {
  return (
    <LegalLayout title="Data Processing Agreement" lastUpdated="November 9, 2026">
      <p style={legalPStyle}>
        This Data Processing Agreement (&quot;DPA&quot;) applies to the
        personal data in the API log data you connect to Clew, and forms part
        of the{" "}
        <Link href="/legal/terms" style={{ color: "var(--color-text)" }}>Terms of Service</Link>.
        You are the controller (in Indian law, the data fiduciary) of that
        data, and Clew Technologies Private Limited (CIN
        U62090KL2026PTC104122) is your processor.
      </p>

      <h2 style={legalH2Style}>1. What is processed and why</h2>
      <p style={legalPStyle}>
        Clew processes the access logs you connect from your Amazon S3
        location: IP addresses, request methods, endpoints, response codes,
        timings and user-agents. It processes them only to detect, explain
        and, where you configure it, block abusive traffic for you, and
        follows your documented instructions given through the product and
        the Terms. It does not use the data for its own purposes or sell it.
      </p>

      <h2 style={legalH2Style}>2. Confidentiality and security</h2>
      <p style={legalPStyle}>
        Clew limits access to your data to people who need it to run the
        service and who are bound by confidentiality. Access to your S3
        bucket is read-only. Passwords are hashed and sensitive credentials
        are encrypted at rest. Clew applies reasonable technical and
        organisational measures to protect the data against unauthorised
        access, loss or disclosure.
      </p>

      <h2 style={legalH2Style}>3. Subprocessors</h2>
      <p style={legalPStyle}>
        Clew uses these subprocessors: Amazon Web Services (hosting),
        Razorpay (payment processing, no log data), Resend (transactional
        email, no log data), MaxMind (IP geolocation lookups) and, for
        Growth plans and above, Groq (plain-language threat explanations,
        which receive the IP address under investigation, aggregated traffic
        metrics and short indicator strings, not raw request bodies). Clew
        stays responsible for its subprocessors and binds each to
        protections no weaker than this DPA. We will tell account owners by
        email before adding a subprocessor that receives log data, and an
        owner who objects can delete the account.
      </p>

      <h2 style={legalH2Style}>4. Retention and deletion</h2>
      <p style={legalPStyle}>
        Detection data is kept for the retention window of your plan and then
        permanently deleted daily, as set out in the{" "}
        <Link href="/legal/privacy" style={{ color: "var(--color-text)" }}>Privacy Policy</Link>.
        When you delete your account, all associated data is deleted within
        30 days, and backups are overwritten within a further 30 days.
        Payment and billing records are kept for 8 years because the law
        requires it, then deleted. You can request deletion of your data through
        the product, or by emailing{" "}
        <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>support@clewsec.com</a>.
      </p>

      <h2 style={legalH2Style}>5. Helping you meet your obligations</h2>
      <p style={legalPStyle}>
        Clew will help you, within reason and on request, to respond to
        requests from the people the data relates to, and to meet your
        security and breach-notification duties. Tell us promptly if a
        request about your data reaches you that we should know about.
      </p>

      <h2 style={legalH2Style}>6. Personal data breach</h2>
      <p style={legalPStyle}>
        If Clew becomes aware of a personal data breach affecting your data,
        it will notify the account owner by email without undue delay and in
        any case within 72 hours, with what is known about the nature of the
        breach, the data involved and the steps being taken.
      </p>

      <h2 style={legalH2Style}>7. Audits</h2>
      <p style={legalPStyle}>
        On written request, Clew will give you the information reasonably
        needed to show that it follows this DPA. An on-site audit needs
        agreed notice and scope, and must not disrupt other customers.
      </p>

      <h2 style={legalH2Style}>8. Signed copy</h2>
      <p style={legalPStyle}>
        This page is the DPA and applies once you accept the Terms. If your
        organisation needs a countersigned PDF, email{" "}
        <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>support@clewsec.com</a>.
      </p>
    </LegalLayout>
  );
}
