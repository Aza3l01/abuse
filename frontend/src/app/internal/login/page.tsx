"use client";

import { useState } from "react";
import { ErrorLine, buttonStyle, inputStyle } from "@/components/internal/ui";
import { StaffApiError, staffPost } from "@/lib/staffApi";

export default function StaffLoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await staffPost("/auth/login", { email, password, code });
      window.location.assign("/");
    } catch (e) {
      setError(e instanceof StaffApiError ? e.message : "Sign in failed.");
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <form
        onSubmit={submit}
        style={{ width: "340px", border: "1px solid var(--color-border)", padding: "24px", display: "grid", gap: "12px" }}
      >
        <div style={{ fontFamily: "var(--font-courier), 'Courier New', monospace", fontSize: "28px" }}>clew</div>
        <div style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-muted)" }}>
          internal sign in
        </div>
        <label style={{ display: "grid", gap: "4px", fontSize: "11px" }}>
          Email
          <input style={inputStyle} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label style={{ display: "grid", gap: "4px", fontSize: "11px" }}>
          Password
          <input
            style={inputStyle}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <label style={{ display: "grid", gap: "4px", fontSize: "11px" }}>
          Authenticator code
          <input
            style={{ ...inputStyle, letterSpacing: "0.2em" }}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </label>
        <ErrorLine message={error} />
        <button type="submit" disabled={busy} style={buttonStyle}>
          {busy ? "Signing in" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
