"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { AuthLayout, inputStyle, labelStyle, primaryBtnStyle } from "@/components/auth/AuthLayout";
import { API_URL } from "@/lib/api";

function VerifyEmailForm() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  // Pre-fill from query param set by the register page or login redirect.
  const prefillEmail = searchParams.get("email") ?? "";

  const [email,    setEmail]    = useState(prefillEmail);
  const [code,     setCode]     = useState("");
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);
  const [resending, setResending] = useState(false);
  const [resendMsg, setResendMsg] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/auth/verify-email`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Verification failed.");
        return;
      }
      router.push("/dashboard");
    } catch {
      setError("Could not connect to the server. Try again.");
    } finally {
      setLoading(false);
    }
  }

  async function handleResend() {
    setResendMsg("");
    setResending(true);
    try {
      await fetch(`${API_URL}/auth/resend-verification`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      setResendMsg("A new code was sent if your email is registered.");
    } catch {
      setResendMsg("Could not send. Check your connection.");
    } finally {
      setResending(false);
    }
  }

  return (
    <AuthLayout title="Verify your email">
      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "20px", lineHeight: 1.5 }}>
        Enter the 6-digit code we sent to your email address. It expires in 15 minutes.
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        <div>
          <label htmlFor="email" style={labelStyle}>Email</label>
          <input
            id="email" type="email" required
            value={email} onChange={(e) => setEmail(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label htmlFor="code" style={labelStyle}>Verification code</label>
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

        {error && (
          <p style={{ fontSize: "13px", color: "#E53E3E", margin: 0 }}>{error}</p>
        )}

        <button type="submit" style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1 }} disabled={loading}>
          {loading ? "Verifying…" : "Verify email"}
        </button>
      </form>

      <div style={{ marginTop: "20px", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <button
          onClick={handleResend}
          disabled={resending || !email}
          style={{
            background: "none", border: "none", padding: 0, cursor: "pointer",
            fontSize: "13px", color: "var(--color-text-muted)", textDecoration: "underline",
          }}
        >
          {resending ? "Sending…" : "Resend code"}
        </button>
        <Link href="/login" style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>
          Back to sign in
        </Link>
      </div>

      {resendMsg && (
        <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginTop: "12px" }}>{resendMsg}</p>
      )}
    </AuthLayout>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmailForm />
    </Suspense>
  );
}
