"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { AuthLayout, inputStyle, labelStyle, primaryBtnStyle } from "@/components/auth/AuthLayout";
import { API_URL } from "@/lib/api";

function ResetPasswordForm() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  const prefillEmail = searchParams.get("email") ?? "";

  const [email,    setEmail]    = useState(prefillEmail);
  const [code,     setCode]     = useState("");
  const [password, setPassword] = useState("");
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);

  // MFA second-factor state (the account's own password is not the second
  // factor, so a successful reset still has to pass the TOTP/backup-code
  // challenge before a session is issued, same as /auth/login)
  const [mfaStep,       setMfaStep]       = useState(false);
  const [mfaToken,      setMfaToken]      = useState("");
  const [mfaCode,       setMfaCode]       = useState("");
  const [useBackupCode, setUseBackupCode] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/auth/reset-password`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code, new_password: password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Reset failed.");
        return;
      }
      if (data.code === "MFA_REQUIRED") {
        setMfaToken(data.mfa_token);
        setMfaStep(true);
        return;
      }
      router.push("/dashboard");
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
      router.push("/dashboard");
    } catch {
      setError("Could not connect to the server. Try again.");
    } finally {
      setLoading(false);
    }
  }

  if (mfaStep) {
    return (
      <AuthLayout title={useBackupCode ? "Use a backup code" : "Two-factor authentication"}>
        <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "20px" }}>
          Your password was reset.{" "}
          {useBackupCode
            ? "Enter one of your 10-character backup codes (e.g. ABCDE-FGHIJ)."
            : "Enter the 6-digit code from your authenticator app to finish signing in."}
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
        </p>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Set a new password">
      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "20px", lineHeight: 1.5 }}>
        Enter the code we sent to your email and choose a new password.
      </p>

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
          <label htmlFor="code" style={labelStyle}>Reset code</label>
          <input
            id="code"
            type="text"
            inputMode="numeric"
            pattern="[0-9]{6}"
            maxLength={6}
            placeholder="123456"
            required
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            style={{ ...inputStyle, fontFamily: "var(--font-mono)", letterSpacing: "0.2em", fontSize: "18px" }}
          />
        </div>
        <div>
          <label htmlFor="password" style={labelStyle}>New password</label>
          <input
            id="password" type="password" autoComplete="new-password" required minLength={8}
            value={password} onChange={(e) => setPassword(e.target.value)}
            style={inputStyle}
          />
        </div>

        {error && (
          <p style={{ fontSize: "13px", color: "#E53E3E", margin: 0 }}>{error}</p>
        )}

        <button type="submit" style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1 }} disabled={loading}>
          {loading ? "Resetting…" : "Set new password"}
        </button>
      </form>

      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginTop: "20px", textAlign: "center" }}>
        <Link href="/forgot-password" style={{ color: "var(--color-text-muted)" }}>
          Request a new code
        </Link>
        {" · "}
        <Link href="/login" style={{ color: "var(--color-text-muted)" }}>
          Back to sign in
        </Link>
      </p>
    </AuthLayout>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetPasswordForm />
    </Suspense>
  );
}
