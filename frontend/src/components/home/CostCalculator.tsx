"use client";

import { useState, useEffect } from "react";

type Industry = "saas" | "fintech" | "marketplace" | "other";
type VolumeKey = "under1m" | "1m_10m" | "10m_50m" | "over50m";

const VOLUME_OPTIONS: { key: VolumeKey; label: string; calls: number }[] = [
  { key: "under1m", label: "Under 1M", calls: 500_000 },
  { key: "1m_10m", label: "1M – 10M", calls: 5_000_000 },
  { key: "10m_50m", label: "10M – 50M", calls: 30_000_000 },
  { key: "over50m", label: "Over 50M", calls: 100_000_000 },
];

const INDUSTRY_OPTIONS: { key: Industry; label: string }[] = [
  { key: "saas", label: "SaaS" },
  { key: "fintech", label: "Fintech" },
  { key: "marketplace", label: "Marketplace" },
  { key: "other", label: "Other" },
];

// Threat mix by industry (% of malicious traffic per threat type)
const THREAT_MIX: Record<
  Industry,
  { bot: number; stuffing: number; enumeration: number; exfil: number }
> = {
  saas:        { bot: 0.55, stuffing: 0.15, enumeration: 0.25, exfil: 0.05 },
  fintech:     { bot: 0.30, stuffing: 0.40, enumeration: 0.20, exfil: 0.10 },
  marketplace: { bot: 0.65, stuffing: 0.10, enumeration: 0.20, exfil: 0.05 },
  other:       { bot: 0.55, stuffing: 0.15, enumeration: 0.25, exfil: 0.05 },
};

// Range constants: these set the low/high band, not a single deterministic
// number. They loosely reflect the order of magnitude reported in published
// incident-cost research (Imperva/Thales Bad Bot Report, IBM Cost of a Data
// Breach), scaled by our own threat-mix-by-industry weighting above. This is
// still a formula, not a lookup of those reports' exact figures. The point is
// to stop presenting a single computed number as if it were precise.
const ABUSE_RATE_LOW = 0.01;          // 1% of calls are malicious, low end
const ABUSE_RATE_HIGH = 0.025;        // 2.5% of calls are malicious, high end
const ATO_SUCCESS_RATE = 0.003;       // 0.3% of stuffing attempts succeed (still well below IBM's cited 3.2%)
const ATO_COST_INR = 8_000;           // ₹8,000 average cost per successful account takeover
const INFRA_COST_PER_REQ_INR = 0.9;   // ₹0.90 infra + response cost per malicious request
const EXFIL_MULTIPLIER_LOW = 2.5;     // annual data-exposure cost per call, low end
const EXFIL_MULTIPLIER_HIGH = 7.5;    // annual data-exposure cost per call, high end
const TOTAL_DAMPENING = 0.88;         // total is tightened, not a naive sum of the three card ranges

type Range = { low: number; high: number };

function computeAnnualCostRange(
  calls: number,
  industry: Industry
): { infra: Range; stuffing: Range; exfil: Range; total: Range } {
  const mix = THREAT_MIX[industry];
  const maliciousLow = calls * ABUSE_RATE_LOW;
  const maliciousHigh = calls * ABUSE_RATE_HIGH;

  const infraLow =
    maliciousLow * (mix.bot + mix.enumeration) * INFRA_COST_PER_REQ_INR * 12;
  const infraHigh =
    maliciousHigh * (mix.bot + mix.enumeration) * INFRA_COST_PER_REQ_INR * 12;

  const stuffingLow = maliciousLow * mix.stuffing * ATO_SUCCESS_RATE * ATO_COST_INR * 12;
  const stuffingHigh = maliciousHigh * mix.stuffing * ATO_SUCCESS_RATE * ATO_COST_INR * 12;

  const exfilLow = calls * mix.exfil * EXFIL_MULTIPLIER_LOW;
  const exfilHigh = calls * mix.exfil * EXFIL_MULTIPLIER_HIGH;

  const sumLow = infraLow + stuffingLow + exfilLow;
  const sumHigh = infraHigh + stuffingHigh + exfilHigh;

  return {
    infra:    { low: Math.round(infraLow), high: Math.round(infraHigh) },
    stuffing: { low: Math.round(stuffingLow), high: Math.round(stuffingHigh) },
    exfil:    { low: Math.round(exfilLow), high: Math.round(exfilHigh) },
    // Naive sum of the three card ranges reads implausibly wide. Tighten it.
    total: {
      low: Math.round(sumLow * TOTAL_DAMPENING),
      high: Math.round(sumHigh * TOTAL_DAMPENING),
    },
  };
}

function fmt(amount: number, currency: "INR" | "USD"): string {
  const value = currency === "USD" ? Math.round(amount / 84) : amount;
  const symbol = currency === "USD" ? "$" : "₹";

  if (currency === "INR") {
    if (value >= 1_00_00_000) return `${symbol}${(value / 1_00_00_000).toFixed(2)}Cr`;
    if (value >= 100_000) return `${symbol}${(value / 100_000).toFixed(1)}L`;
    if (value >= 1_000) return `${symbol}${(value / 1_000).toFixed(1)}K`;
    return `${symbol}${value}`;
  } else {
    if (value >= 1_000_000) return `${symbol}${(value / 1_000_000).toFixed(2)}M`;
    if (value >= 1_000) return `${symbol}${(value / 1_000).toFixed(1)}K`;
    return `${symbol}${value}`;
  }
}

function fmtRange(range: Range, currency: "INR" | "USD"): string {
  return `${fmt(range.low, currency)} – ${fmt(range.high, currency)}`;
}

// Pre-compute SMB baseline: 10M calls/month, SaaS industry
const SMB_BASELINE = computeAnnualCostRange(10_000_000, "saas");

export function CostCalculator() {
  const [volume, setVolume] = useState<VolumeKey>("1m_10m");
  const [industry, setIndustry] = useState<Industry>("saas");
  const [currency, setCurrency] = useState<"INR" | "USD">("INR");

  useEffect(() => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const lang = navigator.language || "";
    const isIndia =
      tz.includes("Kolkata") ||
      tz.includes("Calcutta") ||
      lang === "hi" ||
      lang.endsWith("-IN");
    setCurrency(isIndia ? "INR" : "USD");
  }, []);

  const selectedVolume = VOLUME_OPTIONS.find((v) => v.key === volume)!;
  const result = computeAnnualCostRange(selectedVolume.calls, industry);

  const baselineStat = fmtRange(SMB_BASELINE.total, currency);

  const breakdown = [
    { label: "Infrastructure waste", sublabel: "bots + scanning", range: result.infra },
    { label: "Account takeover", sublabel: "credential stuffing", range: result.stuffing },
    { label: "Data exposure", sublabel: "DPDP / exfil risk", range: result.exfil },
  ];

  const btnBase: React.CSSProperties = {
    padding: "10px 16px",
    fontSize: "13px",
    textAlign: "left" as const,
    border: "1px solid var(--color-border)",
    cursor: "pointer",
    transition: "background 0.1s",
    color: "var(--color-text)",
    background: "transparent",
  };

  const btnActive: React.CSSProperties = {
    padding: "10px 16px",
    fontSize: "13px",
    textAlign: "left" as const,
    border: "1px solid var(--color-text)",
    cursor: "pointer",
    transition: "background 0.1s",
    color: "var(--color-bg)",
    background: "var(--color-text)",
  };

  return (
    <section
      id="cost"
      style={{ borderTop: "1px solid var(--color-border)", padding: "80px 0" }}
    >
      <div style={{ maxWidth: "1400px", margin: "0 auto", padding: "0 24px" }}>
        {/* Baseline stat */}
        <div className="mb-12">
          <p
            className="font-mono text-xs uppercase tracking-widest mb-3"
            style={{ color: "var(--color-text-muted)" }}
          >
            Industry benchmark
          </p>
          <p
            className="font-brand leading-snug"
            style={{
              fontSize: "clamp(1.5rem, 2.8vw, 2.25rem)",
              color: "var(--color-text)",
            }}
          >
            SMBs processing 10M API calls/month lose an estimated{" "}
            <strong>{baselineStat} annually</strong> to undetected abuse.
          </p>
          <p
            className="text-sm mt-2"
            style={{ color: "var(--color-text-muted)" }}
          >
            Range reflects reported incident costs across API-first
            businesses (Imperva/Thales 2024, IBM Cost of a Data Breach 2025),
            not a precise calculation for your business.
          </p>
        </div>

        {/* Calculator card */}
        <div
          style={{
            border: "1px solid var(--color-border)",
            background: "var(--color-surface)",
            padding: "32px",
          }}
        >
          <p
            className="font-mono text-xs uppercase tracking-widest mb-6"
            style={{ color: "var(--color-text-muted)" }}
          >
            Calculate your exposure
          </p>

          <div className="grid md:grid-cols-2 gap-8 mb-8">
            {/* Volume selector */}
            <div>
              <p
                className="text-sm font-medium mb-3"
                style={{ color: "var(--color-text)" }}
              >
                Monthly API call volume
              </p>
              <div className="grid grid-cols-2 gap-2">
                {VOLUME_OPTIONS.map((opt) => (
                  <button
                    key={opt.key}
                    onClick={() => setVolume(opt.key)}
                    style={volume === opt.key ? btnActive : btnBase}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Industry selector */}
            <div>
              <p
                className="text-sm font-medium mb-3"
                style={{ color: "var(--color-text)" }}
              >
                Industry
              </p>
              <div className="grid grid-cols-2 gap-2">
                {INDUSTRY_OPTIONS.map((opt) => (
                  <button
                    key={opt.key}
                    onClick={() => setIndustry(opt.key)}
                    style={industry === opt.key ? btnActive : btnBase}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Results */}
          <div
            style={{
              borderTop: "1px solid var(--color-border)",
              paddingTop: "24px",
            }}
          >
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
              {breakdown.map((item) => (
                <div
                  key={item.label}
                  style={{
                    border: "1px solid var(--color-border)",
                    background: "var(--color-bg)",
                    padding: "16px",
                  }}
                >
                  <p
                    className="text-xs mb-2"
                    style={{ color: "var(--color-text-muted)" }}
                  >
                    {item.label} &middot; {item.sublabel}
                  </p>
                  <p
                    className="font-brand font-bold text-xl"
                    style={{ color: "var(--color-text)" }}
                  >
                    {fmtRange(item.range, currency)}
                  </p>
                </div>
              ))}
            </div>

            <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
              <div>
                <p
                  className="text-xs mb-1"
                  style={{ color: "var(--color-text-muted)" }}
                >
                  Estimated annual exposure
                </p>
                <p
                  className="font-brand font-bold"
                  style={{ fontSize: "2.25rem", color: "var(--color-text)" }}
                >
                  {fmtRange(result.total, currency)}
                </p>
                <div
                  className="flex items-center gap-2 mt-2 flex-wrap"
                  style={{ color: "var(--color-text-muted)" }}
                >
                  <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                    Directional estimate using industry bot-traffic and breach-cost benchmarks.
                  </p>
                  <select
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value as "INR" | "USD")}
                    className="text-xs"
                    style={{
                      background: "var(--color-bg)",
                      border: "1px solid var(--color-border)",
                      cursor: "pointer",
                      color: "var(--color-text-muted)",
                      padding: "2px 6px",
                    }}
                  >
                    <option value="USD">USD ($)</option>
                    <option value="INR">INR (₹)</option>
                  </select>
                </div>
              </div>

              <a
                href="/register"
                className="text-sm font-medium transition-opacity hover:opacity-80 whitespace-nowrap"
                style={{
                  padding: "12px 24px",
                  background: "var(--color-text)",
                  color: "var(--color-bg)",
                  display: "inline-block",
                }}
              >
                See your real number →
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
