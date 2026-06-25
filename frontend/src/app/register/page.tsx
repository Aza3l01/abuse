"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AuthLayout, inputStyle, labelStyle, primaryBtnStyle } from "@/components/auth/AuthLayout";
import { API_URL } from "@/lib/api";

const inviteBanner = (
  <div
    style={{
      padding: "12px 16px",
      background: "#FDE047",
      border: "1px solid #CA8A04",
      borderBottom: "none",
      fontSize: "13px",
      color: "#1a1a1a",
      textAlign: "center",
      lineHeight: 1.5,
    }}
  >
    Clew is currently invite-only.{" "}
    <a
      href="mailto:jeff@clewsec.com"
      style={{ color: "#92400E", textDecoration: "underline", fontWeight: 600 }}
    >
      Click here
    </a>
    {" "}to request access.
  </div>
);

export default function RegisterPage() {
  const router = useRouter();

  const [email,       setEmail]       = useState("");
  const [password,    setPassword]    = useState("");
  const [company,     setCompany]     = useState("");
  const [error,       setError]       = useState("");
  const [loading,     setLoading]     = useState(false);
  const [registered,  setRegistered]  = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/auth/register`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, company_name: company }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Registration failed.");
        return;
      }
      setRegistered(true);
    } catch {
      setError("Could not connect to the server. Try again.");
    } finally {
      setLoading(false);
    }
  }

  if (registered) {
    return (
      <AuthLayout title="Check your email">
        <p style={{ fontSize: "14px", color: "var(--color-text-muted)", lineHeight: 1.6, marginBottom: "20px" }}>
          We sent a 6-digit verification code to <strong style={{ color: "var(--color-text)" }}>{email}</strong>.
          Enter it on the next page to finish setting up your account.
        </p>
        <button
          style={primaryBtnStyle}
          onClick={() => router.push(`/verify-email?email=${encodeURIComponent(email)}`)}
        >
          Enter verification code
        </button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Create your account" banner={inviteBanner}>
      {/* Form — disabled while invite-only */}
      <fieldset
        disabled
        style={{ border: "none", padding: 0, margin: 0, opacity: 0.4 }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <div>
            <label htmlFor="company" style={labelStyle}>Company name</label>
            <input
              id="company" type="text" autoComplete="organization"
              value={company} onChange={(e) => setCompany(e.target.value)}
              style={{ ...inputStyle, cursor: "not-allowed" }}
            />
          </div>
          <div>
            <label htmlFor="email" style={labelStyle}>Work email</label>
            <input
              id="email" type="email" autoComplete="email"
              value={email} onChange={(e) => setEmail(e.target.value)}
              style={{ ...inputStyle, cursor: "not-allowed" }}
            />
          </div>
          <div>
            <label htmlFor="password" style={labelStyle}>Password</label>
            <input
              id="password" type="password" autoComplete="new-password"
              value={password} onChange={(e) => setPassword(e.target.value)}
              style={{ ...inputStyle, cursor: "not-allowed" }}
            />
          </div>
          <button
            type="button"
            style={{ ...primaryBtnStyle, cursor: "not-allowed" }}
          >
            Create account
          </button>
        </div>
      </fieldset>

      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginTop: "20px", textAlign: "center" }}>
        Already have an account?{" "}
        <Link href="/login" style={{ color: "var(--color-text)" }}>
          Sign in
        </Link>
      </p>
    </AuthLayout>
  );
}
