"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { AuthLayout, inputStyle, labelStyle, primaryBtnStyle } from "@/components/auth/AuthLayout";
import { API_URL } from "@/lib/api";

// ── Component ──────────────────────────────────────────────────────────────

function LoginForm() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  const next         = searchParams.get("next") ?? "/dashboard";

  const [email,    setEmail]    = useState("");
  const [password, setPassword] = useState("");
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);

  // MFA second-factor state
  const [mfaStep,       setMfaStep]       = useState(false);
  const [mfaToken,      setMfaToken]      = useState("");
  const [mfaCode,       setMfaCode]       = useState("");
  const [useBackupCode, setUseBackupCode] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        credentials: "include",  // send + receive cookies cross-origin
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        if (res.status === 403) {
          router.push(`/verify-email?email=${encodeURIComponent(email)}`);
          return;
        }
        setError(data.detail ?? "Sign in failed.");
        return;
      }
      if (data.code === "MFA_REQUIRED") {
        setMfaToken(data.mfa_token);
        setMfaStep(true);
        return;
      }
      router.push(next);
    } catch {
      setError("Could not connect to the server. Try again.");
    } finally {
      setLoading(false);
    }
  }

  async function handleMfaSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/auth/login/mfa`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mfa_token: mfaToken, code: mfaCode, is_backup_code: useBackupCode }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Invalid authenticator code.");
        return;
      }
      router.push(next);
    } catch {
      setError("Could not connect to the server. Try again.");
    } finally {
      setLoading(false);
    }
  }

  // ── MFA second-factor screen ──────────────────────────────────────────────
  if (mfaStep) {
    return (
      <AuthLayout title={useBackupCode ? "Use a backup code" : "Two-factor authentication"}>
        <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "20px" }}>
          {useBackupCode
            ? "Enter one of your 10-character backup codes (e.g. ABCDE-FGHIJ)."
            : "Enter the 6-digit code from your authenticator app."}
        </p>
        <form onSubmit={handleMfaSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <div>
            <label style={labelStyle}>{useBackupCode ? "Backup code" : "Authenticator code"}</label>
            <input
              type="text"
              inputMode={useBackupCode ? "text" : "numeric"}
              autoComplete="one-time-code"
              maxLength={useBackupCode ? 11 : 6}
              required
              autoFocus
              value={mfaCode}
              onChange={e => {
                const v = e.target.value;
                setMfaCode(useBackupCode ? v.toUpperCase() : v.replace(/\D/g, ""));
              }}
              placeholder={useBackupCode ? "XXXXX-XXXXX" : ""}
              style={{
                ...inputStyle,
                letterSpacing: useBackupCode ? "0.06em" : "0.3em",
                textAlign: "center",
                fontSize: "18px",
                fontFamily: useBackupCode ? "var(--font-mono)" : "inherit",
              }}
            />
          </div>

          {error && (
            <p style={{ fontSize: "13px", color: "#E53E3E", margin: 0 }}>{error}</p>
          )}

          <button
            type="submit"
            style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1 }}
            disabled={loading}
          >
            {loading ? "Verifying…" : "Verify"}
          </button>
        </form>

        <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginTop: "20px", textAlign: "center" }}>
          <button
            onClick={() => { setUseBackupCode(v => !v); setMfaCode(""); setError(""); }}
            style={{
              background: "none", border: "none",
              color: "var(--color-text-muted)", cursor: "pointer",
              textDecoration: "underline", fontSize: "13px", padding: 0,
            }}
          >
            {useBackupCode ? "Use authenticator app instead" : "Use a backup code"}
          </button>
          {" · "}
          <button
            onClick={() => { setMfaStep(false); setMfaToken(""); setMfaCode(""); setError(""); setUseBackupCode(false); }}
            style={{
              background: "none", border: "none",
              color: "var(--color-text-muted)", cursor: "pointer",
              textDecoration: "underline", fontSize: "13px", padding: 0,
            }}
          >
            Back to sign in
          </button>
        </p>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Log in">

      {/* Credentials form */}
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        <div>
          <label htmlFor="email" style={labelStyle}>Email</label>
          <input
            id="email" type="email" autoComplete="email" required
            value={email} onChange={(e) => setEmail(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "6px" }}>
            <label htmlFor="password" style={{ ...labelStyle, marginBottom: 0 }}>Password</label>
            <Link href="/forgot-password" style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
              Forgot password?
            </Link>
          </div>
          <input
            id="password" type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)}
            style={inputStyle}
          />
        </div>

        {error && (
          <p style={{ fontSize: "13px", color: "#E53E3E", margin: 0 }}>{error}</p>
        )}

        <button type="submit" style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1 }} disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginTop: "20px", textAlign: "center" }}>
        Don&apos;t have an account?{" "}
        <Link href="/register" style={{ color: "var(--color-text)" }}>
          Create one
        </Link>
      </p>
    </AuthLayout>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
