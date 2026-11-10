"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import {
  OPEN_CONSENT_EVENT,
  analyticsConfigured,
  onConsentChange,
  readConsent,
  startAnalytics,
  stopAnalytics,
  writeConsent,
  type Consent,
} from "@/lib/analytics";
import { SITE_URL } from "@/lib/urls";

function subscribeConsent(callback: () => void): () => void {
  return onConsentChange(callback);
}

function readConsentSnapshot(): Consent | "none" {
  return readConsent() ?? "none";
}

const buttonBase: React.CSSProperties = {
  padding: "8px 16px",
  fontSize: "13px",
  fontWeight: 500,
  cursor: "pointer",
  border: "1px solid var(--color-text)",
  background: "transparent",
  color: "var(--color-text)",
  borderRadius: 0,
};

/**
 * Phase 11 consent banner and analytics loader, mounted once in the root
 * layout. Analytics (PostHog EU) starts only after "Accept". The choice is a
 * first-party cookie shared by the marketing and dashboard hosts, so it is
 * asked once. The Cookies section of the privacy page reopens it.
 */
export function Analytics({ enabled }: { enabled: boolean }) {
  const active = enabled && analyticsConfigured;
  // "unknown" during SSR and hydration, then the cookie value.
  const stored = useSyncExternalStore(subscribeConsent, readConsentSnapshot, () => "unknown");
  const [reopened, setReopened] = useState(false);

  useEffect(() => {
    if (active && stored === "granted") startAnalytics();
  }, [active, stored]);

  useEffect(() => {
    if (!active) return;
    const reopen = () => setReopened(true);
    window.addEventListener(OPEN_CONSENT_EVENT, reopen);
    return () => window.removeEventListener(OPEN_CONSENT_EVENT, reopen);
  }, [active]);

  function choose(value: Consent) {
    writeConsent(value);
    setReopened(false);
    if (value === "denied") stopAnalytics();
  }

  if (!active || stored === "unknown" || (stored !== "none" && !reopened)) return null;

  return (
    <section
      aria-label="Cookie consent"
      style={{
        position: "fixed",
        left: "16px",
        right: "16px",
        bottom: "16px",
        maxWidth: "672px",
        zIndex: 90,
        background: "var(--color-bg)",
        color: "var(--color-text)",
        border: "1px solid var(--color-border)",
        padding: "16px",
        fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
      }}
    >
      <p style={{ fontSize: "13px", lineHeight: 1.6, margin: 0 }}>
        We use cookies to improve your experience and analyze site traffic. You can accept or
        decline these cookies. We do not record your sessions or sell your data to advertisers.
        Read our{" "}
        <a href={`${SITE_URL}/legal/privacy`} style={{ color: "var(--color-text)", textDecoration: "underline" }}>
          Privacy Policy
        </a>{" "}
        for more details.
      </p>
      <div style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        <button
          type="button"
          onClick={() => choose("granted")}
          style={buttonBase}
        >
          Accept
        </button>
        <button
          type="button"
          onClick={() => choose("denied")}
          style={buttonBase}
        >
          Decline
        </button>
      </div>
    </section>
  );
}

/** Privacy page control to change the choice later. */
export function CookieSettingsButton({ style }: { style?: React.CSSProperties }) {
  if (!analyticsConfigured) return null;
  return (
    <button
      type="button"
      onClick={() => window.dispatchEvent(new Event(OPEN_CONSENT_EVENT))}
      style={{ background: "none", border: "none", padding: 0, cursor: "pointer", font: "inherit", ...style }}
    >
      Cookie settings
    </button>
  );
}
