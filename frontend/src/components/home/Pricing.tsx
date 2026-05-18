"use client";

import { useState, useEffect } from "react";

type Currency = "INR" | "USD";

interface Tier {
  name: string;
  priceINR: string | null;
  priceUSD: string | null;
  volume: string;
  blocking: boolean;
  features: string[];
  cta: string;
  highlight: boolean;
}

const TIERS: Tier[] = [
  {
    name: "Starter",
    priceINR: "₹9,999/mo",
    priceUSD: "$149/mo",
    volume: "Up to 10M calls/mo",
    blocking: false,
    features: [
      "Detection + dashboard",
      "IP intelligence history",
      "Email alerts on critical threats",
      "AWS API Gateway + ALB support",
    ],
    cta: "Get started",
    highlight: false,
  },
  {
    name: "Growth",
    priceINR: "₹14,999/mo",
    priceUSD: "$249/mo",
    volume: "Up to 50M calls/mo",
    blocking: true,
    features: [
      "Everything in Starter",
      "Auto WAF rule injection",
      "Cloudflare blocking",
      "Slack alerts",
      "Priority support",
    ],
    cta: "Get started",
    highlight: true,
  },
  {
    name: "Pro",
    priceINR: "₹29,999/mo",
    priceUSD: "$449/mo",
    volume: "Up to 200M calls/mo",
    blocking: true,
    features: [
      "Everything in Growth",
      "Custom thresholds",
      "Quarterly business review",
      "Dedicated onboarding",
    ],
    cta: "Get Started",
    highlight: false,
  },
  {
    name: "Enterprise",
    priceINR: null,
    priceUSD: null,
    volume: "Beyond 200M calls/mo",
    blocking: true,
    features: [
      "Everything in Pro",
      "Multi-region support",
      "Custom integrations",
      "SLA guarantee",
      "Dedicated infrastructure",
    ],
    cta: "Contact us",
    highlight: false,
  },
];

const AUDIT_PRICE = { INR: "₹79,999", USD: "$999" };

export function Pricing() {
  const [currency, setCurrency] = useState<Currency>("INR");

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

  return (
    <section
      id="pricing"
      style={{ borderTop: "1px solid var(--color-border)", padding: "80px 0" }}
    >
      <div style={{ maxWidth: "1400px", margin: "0 auto", padding: "0 24px" }}>
        <div className="flex items-end justify-between mb-12 flex-wrap gap-4">
          <div>
            <p
              className="font-mono text-xs uppercase tracking-widest"
              style={{ color: "var(--color-text-muted)" }}
            >
              Pricing
            </p>
          </div>

          <button
            onClick={() => setCurrency(currency === "INR" ? "USD" : "INR")}
            className="text-xs transition-colors"
            style={{
              background: "none",
              border: "1px solid var(--color-border)",
              cursor: "pointer",
              color: "var(--color-text-muted)",
              padding: "6px 12px",
            }}
          >
            View in {currency === "INR" ? "USD" : "INR"}
          </button>
        </div>

        {/* Tier grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-0">
          {TIERS.map((tier, i) => (
            <div
              key={tier.name}
              style={{
                padding: "32px 24px",
                borderTop: "1px solid var(--color-border)",
                borderBottom: "1px solid var(--color-border)",
                borderRight: "1px solid var(--color-border)",
                borderLeft: i === 0 ? "1px solid var(--color-border)" : "none",
                background: tier.highlight
                  ? "var(--color-surface)"
                  : "var(--color-bg)",
                display: "flex",
                flexDirection: "column",
              }}
            >
              {tier.highlight && (
                <p
                  className="font-mono text-xs uppercase tracking-widest mb-4"
                  style={{ color: "var(--color-text-muted)" }}
                >
                  Most popular
                </p>
              )}
              {!tier.highlight && (
                <div style={{ height: tier.name === "Pilot" ? "0" : "28px" }} />
              )}

              <p
                className="font-brand font-bold text-xl mb-2"
                style={{ color: "var(--color-text)" }}
              >
                {tier.name}
              </p>

              {tier.priceINR !== null ? (
                <p
                  className="font-brand font-bold mb-1 whitespace-pre-line"
                  style={{
                    fontSize: "1.5rem",
                    color: "var(--color-text)",
                    lineHeight: "1.3",
                  }}
                >
                  {currency === "INR" ? tier.priceINR : tier.priceUSD}
                </p>
              ) : (
                <p
                  className="font-brand font-bold mb-1"
                  style={{
                    fontSize: "1.1rem",
                    color: "var(--color-text)",
                    lineHeight: "1.3",
                  }}
                >
                  Custom Pricing
                </p>
              )}

              {tier.volume !== "—" && (
                <p
                  className="text-xs mb-6"
                  style={{ color: "var(--color-text-muted)" }}
                >
                  {tier.volume}
                </p>
              )}
              {tier.volume === "—" && <div className="mb-6" />}

              <ul className="flex-1 space-y-2 mb-8">
                {tier.features.map((f) => (
                  <li
                    key={f}
                    className="text-sm flex items-start gap-2"
                    style={{ color: "var(--color-text-muted)" }}
                  >
                    <span style={{ color: "var(--color-text)", flexShrink: 0 }}>
                      —
                    </span>
                    {f}
                  </li>
                ))}
                <li
                  className="text-sm flex items-start gap-2"
                  style={{
                    color: tier.blocking
                      ? "var(--color-text-muted)"
                      : "var(--color-border)",
                  }}
                >
                  <span
                    style={{
                      color: tier.blocking
                        ? "var(--color-text)"
                        : "var(--color-border)",
                      flexShrink: 0,
                    }}
                  >
                    {tier.blocking ? "—" : "×"}
                  </span>
                  Auto blocking
                </li>
              </ul>

              <a
                href="/login"
                className="text-sm font-medium text-center transition-opacity hover:opacity-80"
                style={{
                  padding: "10px 0",
                  background: tier.highlight
                    ? "var(--color-text)"
                    : "transparent",
                  color: tier.highlight
                    ? "var(--color-bg)"
                    : "var(--color-text)",
                  border: tier.highlight
                    ? "none"
                    : "1px solid var(--color-border)",
                  display: "block",
                }}
              >
                {tier.cta}
              </a>
            </div>
          ))}
        </div>

        {/* Clew Audit callout */}
        <div
          className="-mt-px flex flex-col md:flex-row md:items-center justify-between gap-6"
          style={{
            border: "1px solid var(--color-border)",
            background: "var(--color-surface)",
            padding: "24px 32px",
          }}
        >
          <div>
            <p
              className="font-brand font-bold text-lg mb-1"
              style={{ color: "var(--color-text)" }}
            >
              Clew Audit{" "}
              <span
                className="font-mono text-xs font-normal ml-2"
                style={{ color: "var(--color-text-muted)" }}
              >
                one-time
              </span>
            </p>
            <p
              className="text-sm"
              style={{ color: "var(--color-text-muted)", maxWidth: "800px" }}
            >
              {`Full retrospective scan of your entire log history. Surfaces every incident pattern that has ever occurred.`}
              <br />
              {`Delivered as a detailed report in the dashboard.`}
            </p>
          </div>
          <div className="flex items-center gap-6 shrink-0">
            <p
              className="font-brand font-bold text-2xl"
              style={{ color: "var(--color-text)" }}
            >
              {AUDIT_PRICE[currency]}
            </p>
            <a
              href="/login"
              className="text-sm font-medium transition-opacity hover:opacity-80 whitespace-nowrap"
              style={{
                padding: "10px 20px",
                border: "1px solid var(--color-border)",
                color: "var(--color-text)",
              }}
            >
              Request audit
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
