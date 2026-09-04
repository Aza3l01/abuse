"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { AuthLayout, inputStyle, labelStyle, primaryBtnStyle } from "@/components/auth/AuthLayout";
import { apiFetch } from "@/lib/api";

/**
 * Gates all /dashboard/* routes on the current client having at least one
 * organisation. Registration (and OAuth signup) no longer create an org —
 * the first login prompts for a company name here, which creates the org
 * (owner role) via POST /org and becomes the active org immediately.
 */
export function DashboardGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<"loading" | "needs-org" | "ready">("loading");
  const [companyName, setCompanyName] = useState("");
  const [submitting,  setSubmitting]  = useState(false);
  const [error,       setError]       = useState("");

  useEffect(() => {
    apiFetch(`/auth/me`)
      .then(r => {
        if (!r.ok) throw new Error("API error");
        return r.json();
      })
      .then((me: { orgs?: unknown[] } | null) => {
        if (!me) return;
        setStatus(me.orgs && me.orgs.length > 0 ? "ready" : "needs-org");
      })
      .catch(() => setStatus("ready")); // fail open — org-scoped calls below will 403 and surface their own errors
  }, []);

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
      window.location.href = "/dashboard";
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "loading") {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-text-muted)", fontSize: "13px" }}>
        Loading…
      </div>
    );
  }

  if (status === "needs-org") {
    return (
      <AuthLayout title="Set up your organisation">
        <p style={{ fontSize: "14px", color: "var(--color-text-muted)", lineHeight: 1.6, marginBottom: "20px" }}>
          One last step. This creates your organisation — you&apos;ll be its owner,
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
