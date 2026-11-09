"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { staffPost } from "@/lib/staffApi";
import { secondaryButtonStyle } from "@/components/internal/ui";

const LINKS = [
  { href: "/", label: "Accounts" },
  { href: "/pilots", label: "Pilots" },
  { href: "/health", label: "Health" },
  { href: "/metrics", label: "Metrics" },
  { href: "/audit", label: "Audit" },
];

export function InternalShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const onLogin = pathname === "/login" || pathname === "/internal/login";

  async function logout() {
    try {
      await staffPost("/auth/logout", {});
    } finally {
      window.location.assign("/login");
    }
  }

  if (onLogin) return <>{children}</>;

  return (
    <div style={{ minHeight: "100vh", background: "var(--color-bg)", color: "var(--color-text)" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: "16px",
          padding: "12px 24px",
          borderBottom: "1px solid var(--color-border)",
          fontSize: "13px",
        }}
      >
        <span style={{ fontFamily: "var(--font-courier), 'Courier New', monospace", fontSize: "20px" }}>clew</span>
        <span style={{ color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          internal
        </span>
        <nav style={{ display: "flex", gap: "16px", flex: 1 }}>
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              style={{
                color: "var(--color-text)",
                textDecoration: pathname === link.href ? "underline" : "none",
              }}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <button type="button" onClick={logout} style={secondaryButtonStyle}>
          Log out
        </button>
      </header>
      <main style={{ padding: "16px 24px", maxWidth: "1280px", margin: "0 auto" }}>{children}</main>
    </div>
  );
}
