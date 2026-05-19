const AGENTS = [
  {
    label: "volume",
    name: "VolumeAgent",
    description:
      "Isolation Forest on request rates. Detects DoS, DDoS, and flooding before they saturate your infrastructure.",
  },
  {
    label: "temporal",
    name: "TemporalAgent",
    description:
      "FFT + CUSUM drift detection. Finds bot periodicity, scripted polling, and off-hours automation that look human in isolation.",
  },
  {
    label: "auth",
    name: "AuthAgent",
    description:
      "Auth failure pattern analysis. Surfaces brute force, credential stuffing, and password spray before account lockouts cascade.",
  },
  {
    label: "payload",
    name: "PayloadAgent",
    description:
      "Request signature matching. Catches SQL injection, XSS, path traversal, and fuzzing attempts in request paths and parameters.",
  },
  {
    label: "sequence",
    name: "SequenceAgent",
    description:
      "Multi-step chain analysis. Identifies endpoint enumeration and sequential probing: the reconnaissance phase that precedes an actual attack.",
  },
  {
    label: "geoip",
    name: "GeoIPAgent",
    description:
      "Graph-based origin clustering. Flags anomalous source geographies and coordinated distributed attack infrastructure.",
  },
  {
    label: "knowledge",
    name: "KnowledgeAgent",
    description:
      "Cross-session memory. Matches emerging traffic patterns against known threat signatures accumulated across all prior sessions.",
  },
  {
    label: "orchestrator",
    name: "Meta-Agent",
    description:
      "Fuses signals from all seven agents via weighted multi-agent consensus and an XGBoost stacking model. One confidence-scored verdict per batch.",
    isOrchestrator: true,
  },
];

export function AgentsSection() {
  return (
    <section
      style={{ borderTop: "1px solid var(--color-border)", padding: "80px 0" }}
    >
      <div style={{ maxWidth: "1400px", margin: "0 auto", padding: "0 24px" }}>
        <p
          className="font-mono text-xs uppercase tracking-widest mb-6"
          style={{ color: "var(--color-text-muted)" }}
        >
          Detection engine
        </p>

        <h2
          className="font-brand font-bold leading-tight mb-3"
          style={{
            fontSize: "clamp(1.6rem, 2.4vw, 2.2rem)",
            color: "var(--color-text)",
          }}
        >
          Not one classifier. Seven specialised agents.
        </h2>

        <p
          className="text-sm leading-relaxed mb-12"
          style={{ color: "var(--color-text-muted)" }}
        >
          Each agent is independently optimised for a different attack class and runs in parallel against every log batch. The meta-agent orchestrator fuses their signals into a single confidence-scored verdict.
        </p>

        {/* Tight grid: 1px dividers via container background trick */}
        <div
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4"
          style={{
            border: "1px solid var(--color-border)",
            gap: "1px",
            background: "var(--color-border)",
          }}
        >
          {AGENTS.map((agent) => (
            <div
              key={agent.name}
              style={{
                padding: "28px 24px",
                background: agent.isOrchestrator
                  ? "var(--color-surface)"
                  : "var(--color-bg)",
              }}
            >
              <p
                className="font-mono text-xs uppercase tracking-widest mb-3"
                style={{
                  color: agent.isOrchestrator
                    ? "var(--color-text)"
                    : "var(--color-text-muted)",
                }}
              >
                {agent.label}
              </p>
              <p
                className="font-brand font-bold text-base mb-3"
                style={{ color: "var(--color-text)" }}
              >
                {agent.name}
              </p>
              <p
                className="text-sm leading-relaxed"
                style={{ color: "var(--color-text-muted)" }}
              >
                {agent.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
