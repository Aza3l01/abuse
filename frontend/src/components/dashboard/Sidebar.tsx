"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { API_URL } from "@/lib/api";

const NAV = [
  { href: "/dashboard",          label: "Overview" },
  { href: "/dashboard/alerts",   label: "Alerts" },
  { href: "/dashboard/ips",      label: "IPs" },
  { href: "/dashboard/settings", label: "Settings" },
] as const;

export function DashboardSidebar({ company }: { company?: string }) {
  const pathname = usePathname();
  const router   = useRouter();

  async function handleLogout() {
    await fetch(`${API_URL}/auth/logout`, { method: "POST", credentials: "include" });
    router.push("/login");
  }

  return (
    <aside style={{
      width: "192px",
      flexShrink: 0,
      borderRight: "1px solid var(--color-border)",
      display: "flex",
      flexDirection: "column",
      height: "100vh",
      position: "sticky",
      top: 0,
      overflowY: "auto",
    }}>
      {/* Logo */}
      <div style={{ padding: "20px 20px 16px" }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/clew-wordmark-dark.svg"
          alt="Clew"
          style={{ height: "14px", width: "auto", filter: "var(--logo-filter)" }}
        />
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: "0 8px" }}>
        {NAV.map(({ href, label }) => {
          // exact match for /dashboard, prefix match for sub-pages
          const active =
            href === "/dashboard"
              ? pathname === "/dashboard"
              : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              style={{
                display: "block",
                padding: "8px 12px",
                fontSize: "13px",
                color: active ? "var(--color-text)" : "var(--color-text-muted)",
                background: active ? "var(--color-border)" : "transparent",
                textDecoration: "none",
                marginBottom: "2px",
              }}
            >
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div style={{
        padding: "16px 20px",
        borderTop: "1px solid var(--color-border)",
      }}>
        {company && (
          <p style={{
            fontSize: "11px",
            color: "var(--color-text-muted)",
            marginBottom: "8px",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}>
            {company}
          </p>
        )}
        <button
          onClick={handleLogout}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: "12px",
            color: "var(--color-text-muted)",
            padding: 0,
          }}
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
