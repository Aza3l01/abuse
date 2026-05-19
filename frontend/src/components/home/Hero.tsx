"use client";

export function Hero() {
  return (
    <section style={{ maxWidth: "1400px", margin: "0 auto", padding: "96px 24px 64px" }}>
      <div>
        <h1
          className="font-brand font-bold leading-tight mb-6"
          style={{
            fontSize: "clamp(2.5rem, 3.8vw, 4rem)",
            color: "var(--color-text)",
          }}
        >
          API abuse is costing you more than you think.
        </h1>

        <p
          className="text-lg leading-relaxed mb-10"
          style={{ color: "var(--color-text-muted)" }}
        >
          Clew deploys seven specialised AI agents against your AWS API
          Gateway and ALB logs, each independently trained on a different
          attack vector and all running in parallel. Bots, credential
          stuffing, endpoint scanning, data exfiltration. No code changes.
          No proxy. Just connect your S3 logs.
        </p>

        <div className="flex flex-wrap items-center gap-4">
          <button
            onClick={() => document.getElementById("pricing")?.scrollIntoView({ behavior: "smooth" })}
            className="px-6 py-3 text-sm font-medium transition-opacity hover:opacity-80"
            style={{
              background: "var(--color-text)",
              color: "var(--color-bg)",
              border: "none",
              cursor: "pointer",
            }}
          >
            Get started
          </button>
          <a
            href="#cost"
            onClick={(e) => {
              e.preventDefault();
              document.getElementById("cost")?.scrollIntoView({ behavior: "smooth" });
            }}
            className="px-6 py-3 text-sm font-medium transition-colors"
            style={{
              border: "1px solid var(--color-border)",
              color: "var(--color-text)",
            }}
          >
            Calculate your exposure
          </a>
        </div>
      </div>
    </section>
  );
}
