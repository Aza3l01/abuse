"use client";

import { useEffect, useState, Suspense } from "react";
import { apiFetch } from "@/lib/api";
import { VerdictsTab } from "@/components/dashboard/VerdictsTab";
import { NotificationsTab } from "@/components/dashboard/NotificationsTab";

type Tab = "verdicts" | "notifications";

function AlertsInner() {
  const [tab, setTab] = useState<Tab>("verdicts");
  const [role, setRole] = useState<string | null>(null);
  const [alertEmail, setAlertEmail] = useState<string | null>(null);

  useEffect(() => {
    apiFetch(`/clients/me`)
      .then(r => r.ok ? r.json() : null)
      .then(c => {
        if (c) {
          setRole(c.role ?? null);
          setAlertEmail(c.alert_email ?? null);
        }
      })
      .catch(() => {/* viewer role: no /clients/me access, tab still works read-only */});
  }, []);

  return (
    <main style={{ padding: "32px", width: "100%" }}>
      <h1 style={{ fontFamily: "var(--font-brand)", fontSize: "22px", fontWeight: 700, marginBottom: "20px" }}>
        Alerts
      </h1>

      {/* Item 20: Verdicts / Notifications tabs */}
      <div style={{ display: "flex", gap: "4px", marginBottom: "24px", borderBottom: "1px solid var(--color-border)" }}>
        {([
          { key: "verdicts", label: "Verdicts" },
          { key: "notifications", label: "Notifications" },
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

      {tab === "verdicts" ? (
        <VerdictsTab />
      ) : (
        <NotificationsTab role={role} alertEmail={alertEmail} />
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Page: wrap in Suspense for useSearchParams()
// ---------------------------------------------------------------------------

export default function AlertsPage() {
  return (
    <Suspense fallback={
      <main style={{ padding: "32px", color: "var(--color-text-muted)", fontSize: "13px" }}>
        Loading…
      </main>
    }>
      <AlertsInner />
    </Suspense>
  );
}

