"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { API_URL, apiFetch } from "@/lib/api";

const NAV = [
  { href: "/dashboard",          label: "Overview" },
  { href: "/dashboard/alerts",   label: "Alerts" },
  { href: "/dashboard/ips",      label: "IPs" },
  { href: "/dashboard/settings", label: "Settings" },
] as const;

interface OrgRow {
  id: string;
  company_name: string | null;
  role: string;
  active: boolean;
}

export function DashboardSidebar({ company }: { company?: string }) {
  const pathname = usePathname();
  const router   = useRouter();

  const [orgs,        setOrgs]        = useState<OrgRow[]>([]);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [switching,    setSwitching]    = useState(false);

  useEffect(() => {
    apiFetch(`/auth/orgs`)
      .then(r => r.ok ? r.json() : [])
      .then((rows: OrgRow[]) => setOrgs(rows))
      .catch(() => {/* switcher is non-critical */});
  }, []);

  const activeOrg = orgs.find(o => o.active) ?? orgs[0];
  // Settings and team management are hidden from viewers (item 8's RBAC).
  const nav = activeOrg?.role === "viewer" ? NAV.filter(n => n.href !== "/dashboard/settings") : NAV;

  async function handleSwitchOrg(orgId: string) {
    if (orgId === activeOrg?.id) { setSwitcherOpen(false); return; }
    setSwitching(true);
    try {
      await apiFetch(`/auth/switch-org`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ org_id: orgId }),
      });
      window.location.href = "/dashboard";
    } catch {
      setSwitching(false);
    }
  }

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

      {/* Org switcher — basic single-email switcher (item 7's MVP scope;
          the cross-email account switcher is post-MVP) */}
      {orgs.length > 0 && (
        <div style={{ padding: "0 12px 12px", borderBottom: "1px solid var(--color-border)", marginBottom: "8px" }}>
          <button
            onClick={() => setSwitcherOpen(v => !v)}
            disabled={switching}
            style={{
              width: "100%",
              textAlign: "left",
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              color: "var(--color-text)",
              padding: "8px 10px",
              fontSize: "12px",
              cursor: switching ? "default" : "pointer",
            }}
          >
            {activeOrg?.company_name ?? "Select organisation"}
            {orgs.length > 1 && <span style={{ color: "var(--color-text-muted)" }}> ▾</span>}
          </button>
          {switcherOpen && orgs.length > 1 && (
            <div style={{ marginTop: "4px", border: "1px solid var(--color-border)", background: "var(--color-surface)" }}>
              {orgs.map(o => (
                <button
                  key={o.id}
                  onClick={() => handleSwitchOrg(o.id)}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    background: o.active ? "var(--color-border)" : "transparent",
                    border: "none",
                    color: "var(--color-text)",
                    padding: "8px 10px",
                    fontSize: "12px",
                    cursor: "pointer",
                  }}
                >
                  {o.company_name ?? o.id}
                  <span style={{ color: "var(--color-text-muted)" }}> ({o.role})</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Nav */}
      <nav style={{ flex: 1, padding: "0 8px" }}>
        {nav.map(({ href, label }) => {
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
