"use client";

import { useState } from "react";
import Link from "next/link";
import { AuthLayout, inputStyle, labelStyle, primaryBtnStyle } from "@/components/auth/AuthLayout";
import { API_URL } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email,     setEmail]     = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error,     setError]     = useState("");
  const [loading,   setLoading]   = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/auth/forgot-password`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) {
        const data = await res.json();
        if (res.status !== 429) {
          // 429 should still show the "sent if registered" message to avoid enumeration
          setError(data.detail ?? "Something went wrong.");
          return;
        }
      }
      setSubmitted(true);
    } catch {
      setError("Could not connect to the server. Try again.");
    } finally {
      setLoading(false);
    }
  }

  if (submitted) {
    return (
      <AuthLayout title="Check your email">
        <p style={{ fontSize: "14px", color: "var(--color-text-muted)", lineHeight: 1.6, marginBottom: "24px" }}>
          If that email address is registered, we&apos;ve sent a 6-digit reset code.
          It expires in 15 minutes.
        </p>
        <Link
          href={`/reset-password?email=${encodeURIComponent(email)}`}
          style={{ ...primaryBtnStyle, textDecoration: "none", display: "block", textAlign: "center" }}
        >
          Enter reset code
        </Link>
        <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginTop: "16px", textAlign: "center" }}>
          <Link href="/login" style={{ color: "var(--color-text-muted)" }}>Back to sign in</Link>
        </p>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Reset your password">
      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "20px", lineHeight: 1.5 }}>
        Enter your account email. We&apos;ll send a code to reset your password.
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

        {error && (
          <p style={{ fontSize: "13px", color: "#E53E3E", margin: 0 }}>{error}</p>
        )}

        <button type="submit" style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1 }} disabled={loading}>
          {loading ? "Sending…" : "Send reset code"}
        </button>
      </form>

      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginTop: "20px", textAlign: "center" }}>
        <Link href="/login" style={{ color: "var(--color-text-muted)" }}>Back to sign in</Link>
      </p>
    </AuthLayout>
  );
}
