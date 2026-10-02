import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Page not found",
};

export default function NotFound() {
  return (
    <div
      className="flex flex-col min-h-screen items-center justify-center"
      style={{ background: "var(--color-bg)", color: "var(--color-text)", padding: "0 24px" }}
    >
      <p
        className="font-mono text-xs uppercase tracking-widest mb-6"
        style={{ color: "var(--color-text-muted)" }}
      >
        404
      </p>
      <h1
        className="font-brand font-bold mb-4 text-center"
        style={{ fontSize: "clamp(1.5rem, 3vw, 2.5rem)" }}
      >
        This page doesn&apos;t exist.
      </h1>
      <p
        className="text-sm mb-10 text-center"
        style={{ color: "var(--color-text-muted)", maxWidth: "400px" }}
      >
        The link may be broken or the page may have moved.
      </p>
      <Link
        href="/"
        className="text-sm font-medium transition-opacity hover:opacity-80"
        style={{
          padding: "10px 24px",
          border: "1px solid var(--color-border)",
          color: "var(--color-text)",
        }}
      >
        Back to home
      </Link>
    </div>
  );
}
