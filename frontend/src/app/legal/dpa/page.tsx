import type { Metadata } from "next";
import { LegalLayout, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Data Processing Agreement",
  description: "Data Processing Agreement for Clew.",
};

export default function DpaPage() {
  return (
    <LegalLayout title="Data Processing Agreement" lastUpdated="August 10, 2026">
      <p style={legalPStyle}>
        Clew processes customer API log data as a processor on your behalf.
        Our Data Processing Agreement covers what data is processed, how long
        it is retained, which subprocessors are used, and your deletion
        rights.
      </p>
      <p style={legalPStyle}>
        To request a copy of the DPA as a PDF, email{" "}
        <a href="mailto:legal@clewsec.com" style={{ color: "var(--color-text)" }}>legal@clewsec.com</a>.
      </p>
    </LegalLayout>
  );
}
