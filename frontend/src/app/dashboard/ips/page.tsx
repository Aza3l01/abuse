"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { AllIpsTab } from "@/components/dashboard/AllIpsTab";
import { BlockedIpsTab } from "@/components/dashboard/BlockedIpsTab";

type Tab = "all" | "blocked";

export default function IpsPage() {
  const [tab, setTab] = useState<Tab>("all");
  const [role, setRole] = useState<string | null>(null);

  useEffect(() => {
    apiFetch(`/clients/me`)
      .then(r => r.ok ? r.json() : null)
      .then(c => { if (c) setRole(c.role ?? null); })
      .catch(() => {/* viewer role: no /clients/me access, tabs still work read-only */});
  }, []);

  return (
    <main style={{ padding: "32px", width: "100%" }}>
      <h1 style={{ fontFamily: "var(--font-brand)", fontSize: "22px", fontWeight: 700, marginBottom: "20px" }}>
        IPs
      </h1>

      {/* Item 21: All IPs / Blocked tabs */}
      <div style={{ display: "flex", gap: "4px", marginBottom: "24px", borderBottom: "1px solid var(--color-border)" }}>
        {([
          { key: "all", label: "All IPs" },
          { key: "blocked", label: "Blocked" },
        ] as const).map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              padding: "10px 16px",
              fontSize: "13px",
              border: "none",
              borderBottom: tab === t.key ? "2px solid var(--color-text)" : "2px solid transparent",
              background: "transparent",
              color: tab === t.key ? "var(--color-text)" : "var(--color-text-muted)",
              cursor: "pointer",
              marginBottom: "-1px",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "all" ? <AllIpsTab /> : <BlockedIpsTab role={role} />}
    </main>
  );
}
