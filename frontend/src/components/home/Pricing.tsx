"use client";

import { useState, useEffect } from "react";
import { PRICING_TIERS as TIERS, FEATURE_ROWS } from "@/lib/pricing";

type Currency = "INR" | "USD";
type BillingPeriod = "monthly" | "annual";

const AUDIT_PRICE = { INR: "₹49,999", USD: "$599" };

export function Pricing() {
  const [currency, setCurrency] = useState<Currency>("INR");
  const [billingPeriod, setBillingPeriod] = useState<BillingPeriod>("monthly");

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

          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            {/* Billing period toggle */}
            <div style={{ display: "flex", border: "1px solid var(--color-border)" }}>
              <button
                onClick={() => setBillingPeriod("monthly")}
                className="text-xs"
                style={{
                  padding: "6px 12px",
                  background: billingPeriod === "monthly" ? "var(--color-text)" : "var(--color-bg)",
                  color: billingPeriod === "monthly" ? "var(--color-bg)" : "var(--color-text-muted)",
                  border: "none",
                  cursor: "pointer",
                }}
              >
                Monthly
              </button>
              <button
                onClick={() => setBillingPeriod("annual")}
                className="text-xs"
                style={{
                  padding: "6px 12px",
                  background: billingPeriod === "annual" ? "var(--color-text)" : "var(--color-bg)",
                  color: billingPeriod === "annual" ? "var(--color-bg)" : "var(--color-text-muted)",
                  border: "none",
                  cursor: "pointer",
                }}
              >
                Annual -17%
              </button>
            </div>

            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value as Currency)}
              className="text-xs"
              style={{
                background: "var(--color-bg)",
                border: "1px solid var(--color-border)",
                cursor: "pointer",
                color: "var(--color-text-muted)",
                padding: "6px 12px",
              }}
            >
              <option value="USD">USD ($)</option>
              <option value="INR">INR (₹)</option>
            </select>
          </div>
        </div>

        {/* Early Access banner — attached to tier grid */}
        <div
          style={{
            padding: "12px 16px",
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderBottom: "none",
            textAlign: "center",
          }}
        >
          <p style={{ fontFamily: "var(--font-mono)", fontSize: "11px", fontWeight: 700, letterSpacing: "0.1em", color: "var(--color-text)", margin: 0 }}>
            EARLY ACCESS
          </p>
          <p style={{ fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.04em", color: "var(--color-text-muted)", margin: "2px 0 0" }}>
            until 00:00 UTC January 1, 2027
          </p>
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
                <div style={{ height: "28px" }} />
              )}

              <p
                className="font-brand font-bold text-xl mb-2"
                style={{ color: "var(--color-text)" }}
              >
                {tier.name}
              </p>

              {tier.monthlyINR !== null ? (
                <>
                  <p
                    className="font-brand font-bold mb-1"
                    style={{
                      fontSize: "1.5rem",
                      color: "var(--color-text)",
                      lineHeight: "1.3",
                    }}
                  >
                    {billingPeriod === "monthly"
                      ? (currency === "INR" ? tier.monthlyINR : tier.monthlyUSD)
                      : (currency === "INR" ? tier.annualINR : tier.annualUSD)}
                  </p>
                  {billingPeriod === "annual" && (
                    <p
                      className="text-xs mb-1"
                      style={{ color: "var(--color-text-muted)" }}
                    >
                      {currency === "INR" ? tier.annualNoteINR : tier.annualNoteUSD}
                    </p>
                  )}
                </>
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
                {FEATURE_ROWS.map((row) => {
                  const value = row.values[i];
                  const included = value !== false;
                  return (
                    <li
                      key={row.label}
                      className="text-sm flex items-start gap-2"
                      style={{
                        color: included ? "var(--color-text-muted)" : "var(--color-border)",
                      }}
                    >
                      <span
                        style={{
                          color: included ? "var(--color-text)" : "var(--color-border)",
                          flexShrink: 0,
                        }}
                      >
                        {included ? "+" : "×"}
                      </span>
                      {row.label}
                      {typeof value === "string" ? ` (${value})` : ""}
                    </li>
                  );
                })}
              </ul>

              <a
                href={tier.name === "Enterprise" ? "mailto:jeff@clewsec.com" : "/register"}
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
              href="mailto:jeff@clewsec.com"
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
