const STEPS = [
  {
    number: "01",
    heading: "Connect your S3 bucket",
    body: "Grant Clew read-only access to the S3 bucket where your AWS API Gateway or ALB logs are stored. No code changes. No proxy. Just an IAM policy. Takes under two minutes.",
  },
  {
    number: "02",
    heading: "Engine detects threats",
    body: "Our multi-agent detection engine runs every 15 to 30 minutes against your logs. Bots, credential stuffing, endpoint scanning, scrapers, and data exfiltration all detected without you doing anything.",
  },
  {
    number: "03",
    heading: "Dashboard shows findings, optionally blocks",
    body: "Every verdict appears in your dashboard with affected IPs, threat type, confidence, and estimated cost. Growth and Pro clients can enable automatic WAF blocking with one setting.",
  },
];

export function HowItWorks() {
  return (
    <section
      style={{ borderTop: "1px solid var(--color-border)", padding: "80px 0" }}
    >
      <div style={{ maxWidth: "1400px", margin: "0 auto", padding: "0 24px" }}>
        <p
          className="font-mono text-xs uppercase tracking-widest mb-12"
          style={{ color: "var(--color-text-muted)" }}
        >
          How it works
        </p>

        <div className="grid md:grid-cols-3 gap-0">
          {STEPS.map((step, i) => (
            <div
              key={step.number}
              style={{
                padding: "32px",
                borderLeft:
                  i === 0 ? "1px solid var(--color-border)" : undefined,
                borderRight: "1px solid var(--color-border)",
                borderTop: "1px solid var(--color-border)",
                borderBottom: "1px solid var(--color-border)",
              }}
            >
              <p
                className="font-brand font-bold text-4xl mb-6"
                style={{ color: "var(--color-border)" }}
              >
                {step.number}
              </p>
              <h3
                className="font-brand font-bold text-lg mb-3"
                style={{ color: "var(--color-text)", minHeight: "4.5rem", display: "flex", alignItems: "flex-start" }}
              >
                {step.heading}
              </h3>
              <p
                className="text-sm leading-relaxed"
                style={{ color: "var(--color-text-muted)", textAlign: "justify" }}
              >
                {step.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
