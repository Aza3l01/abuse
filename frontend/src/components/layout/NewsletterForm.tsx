"use client";

import { useState } from "react";
import { API_URL } from "@/lib/api";

/**
 * Item 6d: double opt-in newsletter signup, reused in Footer's brand column
 * and the non-INR billing panel (item 6c).
 */
export function NewsletterForm() {
  const [email, setEmail]     = useState("");
  const [website, setWebsite] = useState(""); // honeypot, hidden from real users
  const [state, setState]     = useState<"idle" | "sending" | "done" | "error">("idle");
  const [error, setError]     = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setState("sending");
    setError("");
    try {
      const res = await fetch(`${API_URL}/newsletter/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, website }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setError(d?.detail ?? "Could not subscribe. Please try again.");
        setState("error");
        return;
      }
      setState("done");
    } catch {
      setError("Network error. Please try again.");
      setState("error");
    }
  }

  if (state === "done") {
    return (
      <p style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
        Check your email to confirm your subscription.
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <div style={{ display: "flex", gap: "8px" }}>
        <input
          type="email"
          required
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{
            flex: 1,
            minWidth: 0,
            padding: "8px 10px",
            fontSize: "12px",
            border: "1px solid var(--color-border)",
            background: "var(--color-bg)",
            color: "var(--color-text)",
          }}
        />
        <button
          type="submit"
          disabled={state === "sending"}
          style={{
            padding: "8px 14px",
            fontSize: "12px",
            fontWeight: 500,
            border: "1px solid var(--color-text)",
            background: "var(--color-text)",
            color: "var(--color-bg)",
            cursor: state === "sending" ? "default" : "pointer",
            opacity: state === "sending" ? 0.6 : 1,
            whiteSpace: "nowrap",
          }}
        >
          {state === "sending" ? "Sending…" : "Subscribe"}
        </button>
      </div>

      {/* Honeypot: real users never see this, bots often fill every input. */}
      <input
        type="text"
        name="website"
        value={website}
        onChange={(e) => setWebsite(e.target.value)}
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        style={{ position: "absolute", left: "-9999px", width: "1px", height: "1px", opacity: 0 }}
      />

      {error && (
        <p style={{ fontSize: "11px", color: "var(--color-critical)" }}>{error}</p>
      )}
      <p style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
        Product updates. Unsubscribe any time.
      </p>
    </form>
  );
}
