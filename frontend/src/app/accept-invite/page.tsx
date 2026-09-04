"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { AuthLayout, inputStyle, labelStyle, primaryBtnStyle } from "@/components/auth/AuthLayout";
import { API_URL } from "@/lib/api";

interface InviteInfo {
  valid: boolean;
  reason?: string | null;
  company_name?: string | null;
  role?: string | null;
  invited_email?: string | null;
  account_exists?: boolean | null;
}

function AcceptInviteInner() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") ?? "";

  const [info,      setInfo]      = useState<InviteInfo | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [password,   setPassword]   = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error,      setError]      = useState("");
  const [accepted,   setAccepted]   = useState(false);

  useEffect(() => {
    if (!token) { setLoading(false); return; }
    fetch(`${API_URL}/org/invite/${encodeURIComponent(token)}`)
      .then(r => r.json())
      .then((d: InviteInfo) => setInfo(d))
      .catch(() => setInfo({ valid: false }))
      .finally(() => setLoading(false));
  }, [token]);

  async function handleAccept(e?: React.FormEvent) {
    e?.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/org/invite/${encodeURIComponent(token)}/accept`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(info?.account_exists ? {} : { password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Could not accept this invitation.");
        return;
      }
      setAccepted(true);
      setTimeout(() => router.push("/dashboard"), 1200);
    } catch {
      setError("Could not connect to the server. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <AuthLayout title="Invitation">
        <p style={{ fontSize: "14px", color: "var(--color-text-muted)" }}>Checking your invitation…</p>
      </AuthLayout>
    );
  }

  if (accepted) {
    return (
      <AuthLayout title="Welcome to Clew">
        <p style={{ fontSize: "14px", color: "var(--color-text-muted)", lineHeight: 1.6 }}>
          Invitation accepted. Redirecting to your dashboard…
        </p>
      </AuthLayout>
    );
  }

  if (!token || !info?.valid) {
    const reason = info?.reason;
    const message =
      reason === "expired"
        ? "This invitation has expired. Ask the person who invited you to resend it."
        : reason === "used"
        ? "This invitation has already been accepted."
        : "This invitation link is invalid.";
    return (
      <AuthLayout title="Invitation">
        <p style={{ fontSize: "14px", color: "var(--color-text-muted)", lineHeight: 1.6, marginBottom: "20px" }}>
          {message}
        </p>
        <Link href="/login" style={{ color: "var(--color-text)" }}>
          Go to login →
        </Link>
      </AuthLayout>
    );
  }

  const roleLabel = info.role === "admin" ? "Admin" : "Viewer";

  return (
    <AuthLayout title={`Join ${info.company_name ?? "Clew"}`}>
      <p style={{ fontSize: "14px", color: "var(--color-text-muted)", lineHeight: 1.6, marginBottom: "20px" }}>
        You have been invited to join <strong style={{ color: "var(--color-text)" }}>{info.company_name}</strong>&apos;s
        security dashboard as a <strong style={{ color: "var(--color-text)" }}>{roleLabel}</strong>.
      </p>

      {info.account_exists ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          <p style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>
            Signed in as <strong style={{ color: "var(--color-text)" }}>{info.invited_email}</strong>.
          </p>
          <button style={primaryBtnStyle} onClick={() => handleAccept()} disabled={submitting}>
            {submitting ? "Accepting…" : "Accept invitation"}
          </button>
        </div>
      ) : (
        <form onSubmit={handleAccept}>
          <div style={{ marginBottom: "16px" }}>
            <label style={labelStyle}>Email</label>
            <input type="email" value={info.invited_email ?? ""} readOnly style={{ ...inputStyle, opacity: 0.6 }} />
          </div>
          <div style={{ marginBottom: "20px" }}>
            <label htmlFor="password" style={labelStyle}>Password</label>
            <input
              id="password" type="password" autoComplete="new-password" required
              value={password} onChange={(e) => setPassword(e.target.value)}
              style={inputStyle}
            />
          </div>
          <button type="submit" style={primaryBtnStyle} disabled={submitting}>
            {submitting ? "Setting up…" : "Set password and accept"}
          </button>
        </form>
      )}

      {error && (
        <p style={{ fontSize: "13px", color: "var(--color-critical, #E53E3E)", marginTop: "16px" }}>{error}</p>
      )}
    </AuthLayout>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={null}>
      <AcceptInviteInner />
    </Suspense>
  );
}
