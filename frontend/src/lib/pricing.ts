// Single source of truth for tier prices and feature rows, shared by the
// landing page (components/home/Pricing.tsx) and the dashboard billing
// section (app/dashboard/settings/page.tsx) so the two can never drift apart.
//
// "free" (item 53/section 4, built 2026-09-20) is the permanent free Starter
// plan every self-serve signup lands on: no trial, no card, no expiry.
// `dashboard/settings/page.tsx` still excludes it from its billing cards,
// not because it is unbuilt, but because it is never a purchasable plan.

export interface PricingTier {
  tier: "free" | "starter" | "growth" | "pro" | "enterprise";
  name: string;
  monthlyINR: string | null;
  monthlyUSD: string | null;
  annualINR: string | null;
  annualUSD: string | null;
  annualNoteINR: string | null;
  annualNoteUSD: string | null;
  volume: string;
  cta: string;
  highlight: boolean;
  contactOnly?: boolean;
}

// Internal tier code -> marketing name (e.g. "starter" -> "Basic"). Falls
// back to the raw value for an unrecognized or missing code.
export function tierDisplayName(tier: string | null | undefined): string {
  if (!tier) return "—";
  return PRICING_TIERS.find(t => t.tier === tier)?.name ?? tier;
}

export const PRICING_TIERS: PricingTier[] = [
  {
    tier: "free",
    name: "Starter",
    monthlyINR: "Free",
    monthlyUSD: "Free",
    annualINR: "Free",
    annualUSD: "Free",
    annualNoteINR: null,
    annualNoteUSD: null,
    volume: "Up to 2M calls/mo",
    cta: "Try for free",
    highlight: false,
  },
  {
    tier: "starter",
    name: "Basic",
    monthlyINR: "₹2,999/mo",
    monthlyUSD: "$39/mo",
    annualINR: "₹2,499/mo",
    annualUSD: "$32/mo",
    annualNoteINR: "₹29,988 billed annually",
    annualNoteUSD: "$384 billed annually",
    volume: "Up to 10M calls/mo",
    cta: "Get started",
    highlight: false,
  },
  {
    tier: "growth",
    name: "Growth",
    monthlyINR: "₹4,999/mo",
    monthlyUSD: "$69/mo",
    annualINR: "₹4,166/mo",
    annualUSD: "$57/mo",
    annualNoteINR: "₹49,992 billed annually",
    annualNoteUSD: "$684 billed annually",
    volume: "Up to 50M calls/mo",
    cta: "Get started",
    highlight: true,
  },
  {
    tier: "pro",
    name: "Pro",
    monthlyINR: "₹9,999/mo",
    monthlyUSD: "$129/mo",
    annualINR: "₹8,333/mo",
    annualUSD: "$107/mo",
    annualNoteINR: "₹99,996 billed annually",
    annualNoteUSD: "$1,284 billed annually",
    volume: "Up to 200M calls/mo",
    cta: "Get started",
    highlight: false,
  },
  {
    tier: "enterprise",
    name: "Enterprise",
    monthlyINR: null,
    monthlyUSD: null,
    annualINR: null,
    annualUSD: null,
    annualNoteINR: null,
    annualNoteUSD: null,
    volume: "Beyond 200M calls/mo",
    cta: "Contact us",
    highlight: false,
    contactOnly: true,
  },
];

// Values ordered Starter (free), Basic, Growth, Pro, Enterprise (matches
// PRICING_TIERS above). A string value is shown as the value text itself
// (fully worded, no label prefix), for rows where tiers differ by degree,
// not by plain inclusion.
export interface FeatureRow {
  label: string;
  values: [boolean | string, boolean | string, boolean | string, boolean | string, boolean | string];
}

export const FEATURE_ROWS: FeatureRow[] = [
  { label: "AWS API Gateway + ALB support", values: [true, true, true, true, true] },
  { label: "Detection engine + dashboard", values: [true, true, true, true, true] },
  { label: "IP intelligence history", values: [true, true, true, true, true] },
  { label: "Threat history retention", values: ["7 days history retention", "30 days history retention", "3 months history retention", "1 year history retention", "Unlimited history retention"] },
  { label: "Detection adapts to your traffic over time", values: [false, true, true, true, true] },
  { label: "Email alerts on critical threats", values: [false, true, true, true, true] },
  { label: "Manual IP blocking", values: [false, true, true, true, true] },
  { label: "Auto WAF + Cloudflare blocking", values: [false, false, true, true, true] },
  { label: "Priority support", values: [false, false, true, true, true] },
  { label: "Threat explanations", values: [false, false, true, true, true] },
  { label: "Lower detection confidence threshold", values: [false, false, false, true, true] },
  { label: "Custom thresholds", values: [false, false, false, true, true] },
  { label: "Multi-region support", values: [false, false, false, false, true] },
  { label: "Custom integrations", values: [false, false, false, false, true] },
  { label: "SLA guarantee", values: [false, false, false, false, true] },
  { label: "Dedicated infrastructure", values: [false, false, false, false, true] },
];
