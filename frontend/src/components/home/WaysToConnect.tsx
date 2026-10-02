"use client";

// "Ways to connect" homepage section. Framed around connection METHOD, not
// provider brand, so it never overclaims integrations that do not exist.
// Only the live method is interactive, the rest fade via opacity alone.
const CONNECTION_METHODS = [
  { key: "s3-pull", label: "S3 log pull", live: true },
  { key: "log-push", label: "Direct log push", live: false },
] as const;

export function WaysToConnect() {
  return (
    <section
      style={{ borderTop: "1px solid var(--color-border)", padding: "80px 0" }}
    >
      <div style={{ maxWidth: "1400px", margin: "0 auto", padding: "0 24px" }}>
        <p
          className="font-mono text-xs uppercase tracking-widest mb-6"
          style={{ color: "var(--color-text-muted)" }}
        >
          Ways to connect
        </p>

        <h2
          className="font-brand font-bold leading-tight mb-3"
          style={{
            fontSize: "clamp(1.6rem, 2.4vw, 2.2rem)",
            color: "var(--color-text)",
          }}
        >
          Built around how logs reach us, not which cloud they come from
        </h2>

        <p
          className="text-sm leading-relaxed mb-12"
          style={{ color: "var(--color-text-muted)", maxWidth: "760px" }}
        >
          One connection method is live today. A generic, push-based
          ingestion API that works from any platform is in development.
        </p>

        <div style={{ border: "1px solid var(--color-border)" }}>
          <div
            className="grid grid-cols-2"
            style={{ gap: "1px", background: "var(--color-border)" }}
          >
            {CONNECTION_METHODS.map((method) => (
              <div
                key={method.key}
                style={{
                  padding: "20px 24px",
                  background: "var(--color-bg)",
                  cursor: method.live ? "default" : "not-allowed",
                }}
              >
                <p
                  className="font-mono text-xs uppercase tracking-widest"
                  style={{
                    color: "var(--color-text)",
                    opacity: method.live ? 1 : 0.4,
                  }}
                >
                  {method.label}
                </p>
              </div>
            ))}
          </div>

          <div style={{ padding: "32px", borderTop: "1px solid var(--color-border)" }}>
            <p
              className="text-sm leading-relaxed"
              style={{ color: "var(--color-text-muted)", maxWidth: "1200px" }}
            >
              Clew pulls logs directly from an S3 bucket you control.
              Read-only IAM role, nothing installed on your infrastructure.
              Full setup steps are above, under How It Works.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
