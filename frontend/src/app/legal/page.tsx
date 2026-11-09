import type { Metadata } from "next";
import Link from "next/link";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";

export const metadata: Metadata = {
  title: "Legal Documents",
  description: "Terms, privacy, refund, subscription, and data processing documents for Clew.",
};

const DOCUMENTS = [
  { href: "/legal/terms", title: "Terms of Service", summary: "The terms for using Clew." },
  { href: "/legal/privacy", title: "Privacy Policy", summary: "What data Clew collects and how it is used." },
  { href: "/legal/refund-policy", title: "Refund Policy", summary: "When refunds are and are not available." },
  { href: "/legal/subscription-agreement", title: "Subscription Agreement", summary: "The agreement for the Basic, Growth, and Pro plans." },
  { href: "/legal/dpa", title: "Data Processing Agreement", summary: "How Clew processes your API log data on your behalf." },
];

export default function LegalIndexPage() {
  return (
    <div
      className="flex flex-col min-h-screen"
      style={{ background: "var(--color-bg)", color: "var(--color-text)" }}
    >
      <Navbar />
      <main className="flex-1" style={{ padding: "48px 24px" }}>
        <div style={{ maxWidth: "720px", margin: "0 auto" }}>
          <h1 style={{ fontFamily: "var(--font-brand)", fontSize: "28px", fontWeight: 700, marginBottom: "8px" }}>
            Legal documents
          </h1>
          <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "40px" }}>
            Every legal document for Clew in one place.
          </p>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, borderTop: "1px solid var(--color-border)" }}>
            {DOCUMENTS.map((doc) => (
              <li key={doc.href} style={{ borderBottom: "1px solid var(--color-border)" }}>
                <Link
                  href={doc.href}
                  style={{ display: "block", padding: "16px 0", textDecoration: "none", color: "var(--color-text)" }}
                >
                  <span style={{ display: "block", fontSize: "15px", fontWeight: 600 }}>{doc.title}</span>
                  <span style={{ display: "block", fontSize: "13px", color: "var(--color-text-muted)", marginTop: "4px" }}>
                    {doc.summary}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </main>
      <Footer />
    </div>
  );
}
