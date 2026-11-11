"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { API_URL, apiFetch } from "@/lib/api";
import { SITE_URL } from "@/lib/urls";
import { useIsMobile, MOBILE_TOPBAR_HEIGHT } from "@/lib/useIsMobile";
import { SupportModal } from "@/components/dashboard/SupportModal";

const NAV = [
  { href: "/",                   label: "Overview" },
  { href: "/alerts",             label: "Alerts" },
  { href: "/ips",                label: "IPs" },
  { href: `${SITE_URL}/docs`,     label: "Docs" },
  { href: "/settings",           label: "Settings" },
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
  const isMobile = useIsMobile();

  const [orgs,        setOrgs]        = useState<OrgRow[]>([]);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [switching,    setSwitching]    = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [supportOpen, setSupportOpen] = useState(false);

  useEffect(() => {
    apiFetch(`/auth/orgs`)
      .then(r => r.ok ? r.json() : [])
      .then((rows: OrgRow[]) => setOrgs(rows))
      .catch(() => {/* switcher is non-critical */});
  }, []);

  const activeOrg = orgs.find(o => o.active) ?? orgs[0];
  // Org settings are owner/admin only (item 8's RBAC). Phase 14 (F-024): a
  // viewer keeps the same link, relabelled, because /settings shows them an
  // account-security view (MFA, password, sessions) that the MFA nudge points to.
  const nav = activeOrg?.role === "viewer"
    ? NAV.map(n => n.href === "/settings" ? { ...n, label: "Account security" } : n)
    : NAV;

  async function handleSwitchOrg(orgId: string) {
    if (orgId === activeOrg?.id) { setSwitcherOpen(false); return; }
    setSwitching(true);
    try {
      await apiFetch(`/auth/switch-org`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ org_id: orgId }),
      });
      window.location.assign("/");
    } catch {
      setSwitching(false);
    }
  }

  async function handleLogout() {
    await fetch(`${API_URL}/auth/logout`, { method: "POST", credentials: "include" });
    router.push("/login");
  }

  // Shared org switcher + nav list, reused by both the desktop sidebar and
  // the mobile drawer (closes the drawer on any nav/org click when mobile).
  const orgSwitcher = orgs.length > 0 && (
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
              onClick={() => { handleSwitchOrg(o.id); setMobileNavOpen(false); }}
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
  );

  const navLinks = (
    <nav style={{ flex: 1, padding: "0 8px" }}>
      {nav.map(({ href, label }) => {
        // exact match for /, prefix match for sub-pages
        const active =
          href === "/"
            ? pathname === "/"
            : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={() => setMobileNavOpen(false)}
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
      <button
        onClick={() => { setSupportOpen(true); setMobileNavOpen(false); }}
        style={{
          display: "block",
          width: "100%",
          textAlign: "left",
          padding: "8px 12px",
          fontSize: "13px",
          color: "var(--color-text-muted)",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          marginBottom: "2px",
        }}
      >
        Contact support
      </button>
    </nav>
  );

  const footer = (
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
          fontSize: "15px",
          color: "var(--color-text-muted)",
          padding: 0,
        }}
      >
        Sign out
      </button>
    </div>
  );

  if (isMobile) {
    return (
      <>
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, height: `${MOBILE_TOPBAR_HEIGHT}px`,
          zIndex: 110, display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "0 16px", background: "var(--color-bg)", borderBottom: "1px solid var(--color-border)",
        }}>
          <Link href={SITE_URL} aria-label="Clew home" style={{ display: "flex", alignItems: "center" }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/clew-wordmark-dark.svg"
              alt="Clew"
              style={{ height: "14px", width: "auto", filter: "var(--logo-filter)" }}
            />
          </Link>
          <button
            onClick={() => setMobileNavOpen(v => !v)}
            aria-label={mobileNavOpen ? "Close menu" : "Open menu"}
            style={{
              background: "none", border: "1px solid var(--color-border)", cursor: "pointer",
              padding: "6px 10px", fontSize: "13px", color: "var(--color-text)",
            }}
          >
            {mobileNavOpen ? "Close ×" : "Menu ☰"}
          </button>
        </div>
        {mobileNavOpen && (
          <div style={{
            position: "fixed", top: `${MOBILE_TOPBAR_HEIGHT}px`, left: 0, right: 0, bottom: 0,
            zIndex: 109, background: "var(--color-bg)", overflowY: "auto",
            display: "flex", flexDirection: "column",
          }}>
            {orgSwitcher}
            {navLinks}
            {footer}
          </div>
        )}
        {supportOpen && <SupportModal onClose={() => setSupportOpen(false)} orgId={activeOrg?.id} />}
      </>
    );
  }

  return (
    <>
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
      <div style={{ padding: "20px 20px 16px", display: "flex", alignItems: "center", gap: "8px" }}>
        <Link href={SITE_URL} aria-label="Clew home">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/clew-wordmark-dark.svg"
            alt="Clew"
            style={{ height: "14px", width: "auto", filter: "var(--logo-filter)" }}
          />
        </Link>
        <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>v1.2.1</span>
      </div>

      {/* Org switcher — basic single-email switcher (item 7's MVP scope;
          the cross-email account switcher is post-MVP) */}
      {orgSwitcher}

      {/* Nav */}
      {navLinks}

      {/* Footer */}
      {footer}
    </aside>
    {supportOpen && <SupportModal onClose={() => setSupportOpen(false)} orgId={activeOrg?.id} />}
    </>
  );
}
