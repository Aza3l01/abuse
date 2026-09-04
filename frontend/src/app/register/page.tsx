"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AuthLayout, inputStyle, labelStyle, primaryBtnStyle } from "@/components/auth/AuthLayout";
import { Turnstile } from "@/components/auth/Turnstile";
import { API_URL } from "@/lib/api";
import { passwordStrength, passwordStrengthLabel } from "@/lib/passwordStrength";

export default function RegisterPage() {
  const router = useRouter();

  const [fullName,    setFullName]    = useState("");
  const [email,       setEmail]       = useState("");
  const [password,    setPassword]    = useState("");
  const [company,     setCompany]     = useState("");
  const [pilotCode,   setPilotCode]   = useState("");
  const [tosAccepted, setTosAccepted] = useState(false);
  const [captchaToken, setCaptchaToken] = useState("");
  const [error,       setError]       = useState("");
  const [loading,     setLoading]     = useState(false);
  const [registered,  setRegistered]  = useState(false);

  const strength = passwordStrength(password);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!tosAccepted) {
      setError("You must agree to the Terms of Service and Privacy Policy.");
      return;
    }
    if (!captchaToken) {
      setError("Please complete the CAPTCHA.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/auth/register`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          full_name: fullName,
          company_name: company,
          pilot_code: pilotCode || null,
          captcha_token: captchaToken,
          tos_accepted: tosAccepted,
        }),
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
    <AuthLayout title="Create your account">
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        <div>
          <label htmlFor="fullName" style={labelStyle}>Full name</label>
          <input
            id="fullName" type="text" autoComplete="name" required
            value={fullName} onChange={(e) => setFullName(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label htmlFor="company" style={labelStyle}>Company name</label>
          <input
            id="company" type="text" autoComplete="organization" required
            value={company} onChange={(e) => setCompany(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label htmlFor="email" style={labelStyle}>Work email</label>
          <input
            id="email" type="email" autoComplete="email" required
            value={email} onChange={(e) => setEmail(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label htmlFor="password" style={labelStyle}>Password</label>
          <input
            id="password" type="password" autoComplete="new-password" required
            minLength={8}
            value={password} onChange={(e) => setPassword(e.target.value)}
            style={inputStyle}
          />
          {password.length > 0 && (
            <div style={{ marginTop: "8px" }}>
              <div style={{ display: "flex", gap: "4px" }}>
                {[1, 2, 3, 4].map((seg) => (
                  <div
                    key={seg}
                    style={{
                      height: "3px",
                      flex: 1,
                      background: "var(--color-text)",
                      opacity: seg <= strength ? 1 : 0.15,
                    }}
                  />
                ))}
              </div>
              <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "4px", marginBottom: 0 }}>
                {passwordStrengthLabel[strength]}
              </p>
            </div>
          )}
        </div>
        <div>
          <label htmlFor="pilotCode" style={labelStyle}>Pilot code (optional)</label>
          <input
            id="pilotCode" type="text" autoComplete="off"
            value={pilotCode} onChange={(e) => setPilotCode(e.target.value)}
            style={inputStyle}
          />
        </div>

        <Turnstile onToken={setCaptchaToken} />

        <label style={{ display: "flex", alignItems: "flex-start", gap: "8px", fontSize: "13px", color: "var(--color-text-muted)", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={tosAccepted}
            onChange={(e) => setTosAccepted(e.target.checked)}
            style={{ marginTop: "2px" }}
          />
          <span>
            I agree to the{" "}
            <Link href="/legal/terms" style={{ color: "var(--color-text)" }}>Terms of Service</Link>
            {" "}and{" "}
            <Link href="/legal/privacy" style={{ color: "var(--color-text)" }}>Privacy Policy</Link>
          </span>
        </label>

        {error && (
          <p style={{ fontSize: "13px", color: "#E53E3E", margin: 0 }}>{error}</p>
        )}

        <button type="submit" style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1 }} disabled={loading}>
          {loading ? "Creating account…" : "Create account"}
        </button>
      </form>

      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginTop: "20px", textAlign: "center" }}>
        Already have an account?{" "}
        <Link href="/login" style={{ color: "var(--color-text)" }}>
          Sign in
        </Link>
      </p>
    </AuthLayout>
  );
}
