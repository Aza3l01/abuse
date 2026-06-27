import type { ReactNode } from "react";
import Link from "next/link";

interface AuthLayoutProps {
  title: string;
  children: ReactNode;
  /** Optional banner rendered between the wordmark and the card, visually attached to the card top. */
  banner?: ReactNode;
}

/**
 * Shared wrapper for all auth pages (login, register, verify-email, etc.)
 * Centered card, Clew wordmark at top, no marketing navigation.
 */
export function AuthLayout({ title, children, banner }: AuthLayoutProps) {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
        background: "var(--color-bg)",
      }}
    >
      {/* Logo */}
      <Link href="/" style={{ marginBottom: "32px", display: "block" }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/clew-wordmark-dark.svg"
          alt="Clew"
          style={{ height: "18px", width: "auto", filter: "var(--logo-filter)" }}
        />
      </Link>

      {/* Banner — attached to top of card (no bottom border so card border closes it) */}
      {banner && (
        <div style={{ width: "100%", maxWidth: "400px" }}>
          {banner}
        </div>
      )}

      {/* Card */}
      <div
        style={{
          width: "100%",
          maxWidth: "400px",
          border: "1px solid var(--color-border)",
          background: "var(--color-surface)",
          padding: "32px",
        }}
      >
        <h1
          style={{
            fontFamily: "var(--font-brand)",
            fontSize: "18px",
            fontWeight: 700,
            marginBottom: "24px",
            color: "var(--color-text)",
            textAlign: "center",
          }}
        >
          {title}
        </h1>
        {children}
      </div>
    </div>
  );
}

// ── Reusable primitives ─────────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  padding: "10px 12px",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "14px",
  outline: "none",
  boxSizing: "border-box",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: "11px",
  textTransform: "uppercase",
  letterSpacing: "0.07em",
  color: "var(--color-text-muted)",
  marginBottom: "6px",
};

const primaryBtnStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  padding: "10px",
  background: "var(--color-text)",
  color: "var(--color-bg)",
  border: "none",
  fontSize: "14px",
  cursor: "pointer",
  textAlign: "center",
};

const oauthBtnStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: "8px",
  width: "100%",
  padding: "10px",
  background: "transparent",
  border: "1px solid var(--color-border)",
  color: "var(--color-text)",
  fontSize: "14px",
  cursor: "pointer",
};

const dividerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "12px",
  marginTop: "20px",
  marginBottom: "20px",
};

export {
  inputStyle,
  labelStyle,
  primaryBtnStyle,
  oauthBtnStyle,
  dividerStyle,
};
