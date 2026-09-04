"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { onSessionExpired } from "@/lib/api";
import { primaryBtnStyle } from "@/components/auth/AuthLayout";

/**
 * Item 14 — inline modal overlay shown when a silent refresh (apiFetch)
 * fails. Deliberately not a full-page redirect so it doesn't destroy
 * unsaved form state elsewhere on the page.
 */
export function SessionExpiredModal() {
  const [show, setShow] = useState(false);
  const router = useRouter();

  useEffect(() => onSessionExpired(() => setShow(true)), []);

  if (!show) return null;

  function handleLogin() {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    router.push(`/login?next=${next}`);
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(13, 13, 13, 0.6)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: "24px",
      }}
    >
      <div
        style={{
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          padding: "32px",
          maxWidth: "360px",
          width: "100%",
        }}
      >
        <p style={{ fontSize: "14px", color: "var(--color-text)", marginBottom: "20px", lineHeight: 1.5 }}>
          Your session has expired. Please log in again.
        </p>
        <button style={primaryBtnStyle} onClick={handleLogin}>
          Log in
        </button>
      </div>
    </div>
  );
}
