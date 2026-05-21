"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { AuthLayout, inputStyle, labelStyle, primaryBtnStyle, oauthBtnStyle, dividerStyle } from "@/components/auth/AuthLayout";
import { API_URL } from "@/lib/api";

// ── SVG icons (monochrome) ─────────────────────────────────────────────────

const GoogleIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
  </svg>
);

const GitHubIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
  </svg>
);

const MicrosoftIcon = () => (
  <svg width="16" height="16" viewBox="0 0 21 21" fill="currentColor">
    <path d="M0 0h10v10H0V0zm11 0h10v10H11V0zM0 11h10v10H0V11zm11 0h10v10H11V11z" />
  </svg>
);

// ── Component ──────────────────────────────────────────────────────────────

function LoginForm() {
  const router      = useRouter();
  const searchParams = useSearchParams();
  const next        = searchParams.get("next") ?? "/dashboard";
  const oauthError  = searchParams.get("error");

  const [email,    setEmail]    = useState("");
  const [password, setPassword] = useState("");
  const [error,    setError]    = useState(oauthError ? "OAuth sign-in failed. Please try again." : "");
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
        body: JSON.stringify({ mfa_token: mfaToken, code: mfaCode }),
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

  const handleOAuth = (provider: string) =>
    (window.location.href = `${API_URL}/auth/${provider}`);

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

      {/* OAuth buttons */}
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        <button style={oauthBtnStyle} onClick={() => handleOAuth("google")}>
          <GoogleIcon /> Continue with Google
        </button>
        <button style={oauthBtnStyle} onClick={() => handleOAuth("github")}>
          <GitHubIcon /> Continue with GitHub
        </button>
        <button style={oauthBtnStyle} onClick={() => handleOAuth("microsoft")}>
          <MicrosoftIcon /> Continue with Microsoft
        </button>
      </div>

      {/* Divider */}
      <div style={dividerStyle}>
        <div style={{ flex: 1, height: "1px", background: "var(--color-border)" }} />
        <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>or</span>
        <div style={{ flex: 1, height: "1px", background: "var(--color-border)" }} />
      </div>

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
