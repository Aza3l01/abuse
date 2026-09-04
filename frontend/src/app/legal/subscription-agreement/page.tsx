import type { Metadata } from "next";
import { LegalLayout, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Subscription Agreement",
  description: "Subscription Agreement for Clew — Starter, Growth, and Pro plans.",
};

export default function SubscriptionAgreementPage() {
  return (
    <LegalLayout title="Subscription Agreement" lastUpdated="August 10, 2026">
      <p style={legalPStyle}>
        The full subscription terms for Starter, Growth, and Pro plans
        (usage terms, S3 access scope, blocking-consent terms, and liability
        caps for each plan) are being finalised.
      </p>
      <p style={legalPStyle}>
        To request the current subscription agreement, email{" "}
        <a href="mailto:legal@clewsec.com" style={{ color: "var(--color-text)" }}>legal@clewsec.com</a>.
      </p>
    </LegalLayout>
  );
}
