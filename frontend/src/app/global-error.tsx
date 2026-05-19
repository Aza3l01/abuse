"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log to your error tracking service here if you add one later
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "100vh",
            background: "var(--color-bg, #0a0a0a)",
            color: "var(--color-text, #f5f5f5)",
            padding: "0 24px",
            fontFamily: "system-ui, sans-serif",
          }}
        >
          <p
            style={{
              fontFamily: "monospace",
              fontSize: "11px",
              textTransform: "uppercase",
              letterSpacing: "0.1em",
              color: "var(--color-text-muted, #888)",
              marginBottom: "24px",
            }}
          >
            Something went wrong
          </p>
          <h1
            style={{
              fontSize: "clamp(1.25rem, 2.5vw, 2rem)",
              fontWeight: 700,
              marginBottom: "12px",
              textAlign: "center",
            }}
          >
            An unexpected error occurred.
          </h1>
          <p
            style={{
              fontSize: "14px",
              color: "var(--color-text-muted, #888)",
              marginBottom: "40px",
              textAlign: "center",
              maxWidth: "400px",
            }}
          >
            Try refreshing the page. If the problem persists, contact support.
          </p>
          <div style={{ display: "flex", gap: "12px" }}>
            <button
              onClick={reset}
              style={{
                padding: "10px 24px",
                fontSize: "13px",
                cursor: "pointer",
                border: "1px solid var(--color-border, #333)",
                background: "var(--color-text, #f5f5f5)",
                color: "var(--color-bg, #0a0a0a)",
              }}
            >
              Try again
            </button>
            <a
              href="/"
              style={{
                padding: "10px 24px",
                fontSize: "13px",
                border: "1px solid var(--color-border, #333)",
                color: "var(--color-text, #f5f5f5)",
                textDecoration: "none",
              }}
            >
              Back to home
            </a>
          </div>
        </div>
      </body>
    </html>
  );
}
