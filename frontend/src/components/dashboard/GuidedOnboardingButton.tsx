"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { requestOnboardingOpen } from "@/lib/onboarding";

interface OrgRow {
  id: string;
  role: string;
  active: boolean;
}

/**
 * Re-opens the guided onboarding wizard (see OnboardingModal.tsx). Renders
 * nothing for a viewer, since a viewer can't complete any onboarding step
 * (Phase 4c): showing a button that opens a wizard they can't act on would
 * be a control that silently does nothing.
 */
export function GuidedOnboardingButton({ label = "Guided onboarding" }: { label?: string }) {
  const [role, setRole] = useState<string | null>(null);

  useEffect(() => {
    apiFetch(`/auth/orgs`)
      .then(r => r.ok ? r.json() : [])
      .then((rows: OrgRow[]) => {
        const active = rows.find(o => o.active) ?? rows[0];
        setRole(active?.role ?? null);
      })
      .catch(() => {/* button just stays hidden */});
  }, []);

  if (role === "viewer" || role === null) return null;

  return (
    <button
      onClick={() => requestOnboardingOpen()}
      style={{
        padding: "8px 20px",
        fontSize: "13px",
        border: "1px solid var(--color-text)",
        background: "var(--color-text)",
        color: "var(--color-bg)",
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );
}
