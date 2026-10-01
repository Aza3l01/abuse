import type { Metadata } from "next";
import { LegalLayout, legalH2Style, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Subscription Agreement",
  description: "Subscription Agreement for Clew, Basic, Growth, and Pro plans.",
};

export default function SubscriptionAgreementPage() {
  return (
    <LegalLayout title="Subscription Agreement" lastUpdated="October 1, 2026">
      <p style={legalPStyle}>
        The full subscription terms for Basic, Growth, and Pro plans
        (usage terms, S3 access scope, blocking-consent terms, and liability
        caps for each plan) are being finalised. The free Starter plan has no
        blocking and no subscription, it is not covered by this agreement.
      </p>
      <p style={legalPStyle}>
        To request the current subscription agreement, email{" "}
        <a href="mailto:support@clewsec.com" style={{ color: "var(--color-text)" }}>support@clewsec.com</a>.
      </p>

      <h2 style={legalH2Style}>Legal entity</h2>
      <p style={legalPStyle}>
        This agreement, once finalised, will be issued by Clew Technologies
        Private Limited (CIN U62090KL2026PTC104122), a private limited
        company incorporated in India.
      </p>
    </LegalLayout>
  );
}
