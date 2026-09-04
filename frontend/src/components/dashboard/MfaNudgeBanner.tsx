"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

/**
 * Item 10 Step 3 — dismissible nudge shown on the dashboard until the
 * client either enables MFA or dismisses it. Not a blocking modal.
 */
export function MfaNudgeBanner() {
  const [show, setShow] = useState(false);
  const [dismissing, setDismissing] = useState(false);

  useEffect(() => {
    apiFetch(`/auth/me`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && !data.mfa_enabled && !data.mfa_nudge_dismissed_at) {
          setShow(true);
        }
      })
      .catch(() => {});
  }, []);

  async function dismiss() {
    setDismissing(true);
    try {
      await apiFetch(`/auth/mfa/nudge-dismiss`, {
        method: "POST",
      });
    } catch {
      // best-effort — still hide locally either way
    } finally {
      setShow(false);
      setDismissing(false);
    }
  }

  if (!show) return null;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "16px",
        padding: "12px 24px",
        borderBottom: "1px solid var(--color-border)",
        background: "var(--color-surface)",
        fontSize: "13px",
        color: "var(--color-text)",
      }}
    >
      <span>
        Secure your account — enable two-factor authentication.{" "}
        <Link href="/dashboard/settings#mfa" style={{ color: "var(--color-text)", textDecoration: "underline" }}>
          Set up MFA
        </Link>
      </span>
      <button
        onClick={dismiss}
        disabled={dismissing}
        style={{
          background: "none", border: "none", cursor: "pointer",
          fontSize: "13px", color: "var(--color-text-muted)", textDecoration: "underline",
          padding: 0, flexShrink: 0,
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
