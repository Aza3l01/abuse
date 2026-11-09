"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { apiFetch, getLastApiError } from "@/lib/api";

const SUPPORT_EMAIL = "support@clewsec.com";

/**
 * Support dialog. Shows the correlation id of the most recent failed API
 * call this tab made (if any), so the customer can quote it and support can
 * find the matching server log line.
 */
export function SupportModal({ onClose, orgId }: { onClose: () => void; orgId?: string }) {
  const pathname = usePathname();
  const [copied, setCopied] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  // Read once on mount: the dialog is mounted only while it is open.
  const [last] = useState(() => getLastApiError());

  useEffect(() => {
    let cancelled = false;
    apiFetch("/auth/me")
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (!cancelled && d?.email) setEmail(d.email); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const subject = last ? `Clew support, reference ${last.id}` : "Clew support";
  const context = [
    orgId ? `Organisation: ${orgId}` : null,
    email ? `Account: ${email}` : null,
    `Page: ${pathname}`,
  ].filter(Boolean).join("\n");
  const body = last
    ? `Reference: ${last.id}\nFailed request: ${last.path} (status ${last.status})\n${context}\n\nWhat happened:\n`
    : `${context}\n\nWhat happened:\n`;
  const mailto = `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

  function copy() {
    if (!last) return;
    navigator.clipboard?.writeText(last.id).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Contact support"
      onClick={onClose}
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
        onClick={e => e.stopPropagation()}
        style={{
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          padding: "28px",
          maxWidth: "440px",
          width: "100%",
          animation: "modal-panel-in 150ms ease-out",
        }}
      >
        <p style={{ fontSize: "16px", fontWeight: 700, marginBottom: "8px" }}>Contact support</p>
        <p style={{ fontSize: "13px", color: "var(--color-text-muted)", lineHeight: 1.5, marginBottom: "16px" }}>
          Email <a href={mailto} style={{ color: "var(--color-text)" }}>{SUPPORT_EMAIL}</a> and describe what
          you were doing. If something failed, include the reference below so we can find it in our logs.
        </p>

        <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--color-text-muted)", marginBottom: "6px" }}>
          Reference for the last error
        </p>
        {last ? (
          <div style={{ border: "1px solid var(--color-border)", background: "var(--color-bg)", padding: "10px 12px", marginBottom: "16px" }}>
            <p style={{ fontFamily: "var(--font-mono)", fontSize: "12px", wordBreak: "break-all", marginBottom: "4px" }}>{last.id}</p>
            <p style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
              {last.path}, status {last.status}
            </p>
          </div>
        ) : (
          <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "16px" }}>
            No failed request in this tab yet.
          </p>
        )}

        <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end", flexWrap: "wrap" }}>
          {last && (
            <button
              onClick={copy}
              style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
            >
              {copied ? "Copied" : "Copy reference"}
            </button>
          )}
          <a
            href={mailto}
            style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-text)", background: "var(--color-text)", color: "var(--color-bg)", textDecoration: "none" }}
          >
            Email support
          </a>
          <button
            onClick={onClose}
            style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
