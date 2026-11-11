"use client";

import { useRef, useState } from "react";
import { Turnstile, type TurnstileHandle } from "@/components/auth/Turnstile";
import { API_URL } from "@/lib/api";

/**
 * Item 6d: double opt-in newsletter signup, reused in Footer's brand column
 * and the non-INR billing panel (item 6c).
 *
 * Phase 12b: the subscribe call needs a Turnstile token. The widget (and
 * Cloudflare's script) only loads once the visitor focuses the email box, so
 * a page view that never touches the form makes no third-party request.
 */
export function NewsletterForm() {
  const [email, setEmail]     = useState("");
  const [website, setWebsite] = useState(""); // honeypot, hidden from real users
  const [state, setState]     = useState<"idle" | "sending" | "done" | "error">("idle");
  const [error, setError]     = useState("");
  const [engaged, setEngaged] = useState(false);
  const [captchaToken, setCaptchaToken] = useState("");
  const captchaRef = useRef<TurnstileHandle>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!captchaToken) {
      setError(
        "Complete the CAPTCHA first. If the check does not appear, a script blocker or privacy extension may be stopping it: allow challenges.cloudflare.com for this site and reload the page."
      );
      setState("error");
      return;
    }
    setState("sending");
    setError("");
    try {
      const res = await fetch(`${API_URL}/newsletter/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, website, captcha_token: captchaToken }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        // A token is single use: ask for a fresh challenge after a failure.
        captchaRef.current?.reset();
        setError(typeof d?.detail === "string" ? d.detail : "Could not subscribe. Please try again.");
        setState("error");
        return;
      }
      setState("done");
    } catch {
      captchaRef.current?.reset();
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
          onFocus={() => setEngaged(true)}
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

      {engaged && <Turnstile ref={captchaRef} onToken={setCaptchaToken} />}

      {error && (
        <p style={{ fontSize: "11px", color: "var(--color-critical)" }}>{error}</p>
      )}
      <p style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
        Product updates. Unsubscribe any time.
      </p>
    </form>
  );
}
