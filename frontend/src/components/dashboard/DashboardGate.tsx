"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { AuthLayout, inputStyle, labelStyle, primaryBtnStyle } from "@/components/auth/AuthLayout";
import { apiFetch } from "@/lib/api";
import { identifyUser } from "@/lib/analytics";
import { LoadingCursor } from "@/components/dashboard/LoadingCursor";

interface OrgChoice {
  id: string;
  company_name: string | null;
  role: string;
  active: boolean;
}

/**
 * Gates all /dashboard/* routes on the current client having at least one
 * organisation. Registration (and OAuth signup) no longer create an org,
 * the first login prompts for a company name here, which creates the org
 * (owner role) via POST /org and becomes the active org immediately.
 *
 * Phase 9: an account that belongs to several organisations (an existing
 * account that accepted invites) has no active org after signing out and in
 * again, so every org-scoped call would 403. In that case show a plain list of
 * its organisations and select one via POST /auth/switch-org.
 */
export function DashboardGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<"loading" | "needs-org" | "pick-org" | "ready">("loading");
  const [choices,      setChoices]      = useState<OrgChoice[]>([]);
  const [picking,      setPicking]      = useState<string | null>(null);
  const [companyName, setCompanyName] = useState("");
  const [submitting,  setSubmitting]  = useState(false);
  const [error,       setError]       = useState("");

  useEffect(() => {
    apiFetch(`/auth/me`)
      .then(r => {
        if (!r.ok) throw new Error("API error");
        return r.json();
      })
      .then(async (me: { id?: string; orgs?: unknown[] } | null) => {
        if (!me) return;
        // Same UUID the backend business events use, so web and server events join.
        if (me.id) identifyUser(me.id);
        const count = me.orgs?.length ?? 0;
        if (count === 0) {
          setStatus("needs-org");
          return;
        }
        if (count > 1) {
          const res = await apiFetch(`/auth/orgs`);
          if (res.ok) {
            const rows: OrgChoice[] = await res.json();
            if (rows.length > 1 && !rows.some(o => o.active)) {
              setChoices(rows);
              setStatus("pick-org");
              return;
            }
          }
        }
        setStatus("ready");
      })
      .catch(() => setStatus("ready")); // fail open: org-scoped calls below will 403 and surface their own errors
  }, []);

  async function handlePickOrg(orgId: string) {
    setPicking(orgId);
    setError("");
    try {
      const res = await apiFetch(`/auth/switch-org`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ org_id: orgId }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data?.detail ?? "Could not switch organisation.");
        setPicking(null);
        return;
      }
      window.location.assign("/");
    } catch {
      setError("Network error. Please try again.");
      setPicking(null);
    }
  }

  async function handleCreateOrg(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const res = await apiFetch(`/org`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company_name: companyName }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data?.detail ?? "Could not create your organisation.");
        return;
      }
      window.location.href = "/";
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "loading") {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-text-muted)", fontSize: "13px" }}>
        Loading<LoadingCursor />
      </div>
    );
  }

  if (status === "pick-org") {
    return (
      <AuthLayout title="Choose an organisation">
        <p style={{ fontSize: "14px", color: "var(--color-text-muted)", lineHeight: 1.6, marginBottom: "20px" }}>
          This account belongs to more than one organisation. Pick the one to open.
          You can switch later from the sidebar.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {choices.map(o => (
            <button
              key={o.id}
              onClick={() => handlePickOrg(o.id)}
              disabled={picking !== null}
              style={{
                textAlign: "left",
                padding: "12px 14px",
                fontSize: "14px",
                border: "1px solid var(--color-border)",
                background: "var(--color-surface)",
                color: "var(--color-text)",
                cursor: picking !== null ? "default" : "pointer",
                opacity: picking !== null && picking !== o.id ? 0.5 : 1,
              }}
            >
              {o.company_name ?? o.id}
              <span style={{ color: "var(--color-text-muted)" }}>{` (${o.role})`}</span>
            </button>
          ))}
        </div>
        {error && (
          <p style={{ fontSize: "13px", color: "var(--color-critical, #E53E3E)", marginTop: "16px" }}>{error}</p>
        )}
      </AuthLayout>
    );
  }

  if (status === "needs-org") {
    return (
      <AuthLayout title="Set up your organisation">
        <p style={{ fontSize: "14px", color: "var(--color-text-muted)", lineHeight: 1.6, marginBottom: "20px" }}>
          One last step. This creates your organisation, and you&apos;ll be its owner,
          with full control over billing, configuration, and team members.
        </p>
        <form onSubmit={handleCreateOrg}>
          <div style={{ marginBottom: "20px" }}>
            <label htmlFor="company_name" style={labelStyle}>Company name</label>
            <input
              id="company_name" type="text" autoComplete="organization" required
              value={companyName} onChange={(e) => setCompanyName(e.target.value)}
              style={inputStyle}
            />
          </div>
          <button type="submit" style={primaryBtnStyle} disabled={submitting}>
            {submitting ? "Creating…" : "Create organisation"}
          </button>
        </form>
        {error && (
          <p style={{ fontSize: "13px", color: "var(--color-critical, #E53E3E)", marginTop: "16px" }}>{error}</p>
        )}
      </AuthLayout>
    );
  }

  return <>{children}</>;
}
