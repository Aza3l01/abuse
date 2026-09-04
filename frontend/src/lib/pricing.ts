// Single source of truth for tier prices and feature rows, shared by the
// landing page (components/home/Pricing.tsx) and the dashboard billing
// section (app/dashboard/settings/page.tsx) so the two can never drift apart.

export interface PricingTier {
  tier: "starter" | "growth" | "pro" | "enterprise";
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

export const PRICING_TIERS: PricingTier[] = [
  {
    tier: "starter",
    name: "Starter",
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

// Values ordered Starter, Growth, Pro, Enterprise (matches PRICING_TIERS
// above). A string value is shown as "Label (value)" instead of a plain
// check, for features where the tiers differ by degree, not by inclusion.
export interface FeatureRow {
  label: string;
  values: [boolean | string, boolean | string, boolean | string, boolean | string];
}

export const FEATURE_ROWS: FeatureRow[] = [
  { label: "AWS API Gateway + ALB support", values: [true, true, true, true] },
  { label: "Detection engine + dashboard", values: [true, true, true, true] },
  { label: "IP intelligence history", values: [true, true, true, true] },
  { label: "Threat history retention", values: ["90 days", "1 year", "3 years", "Unlimited"] },
  { label: "Email alerts on critical threats", values: [true, true, true, true] },
  { label: "Auto WAF + Cloudflare blocking", values: [false, true, true, true] },
  { label: "Priority support", values: [false, true, true, true] },
  { label: "Lower detection confidence threshold", values: [false, false, true, true] },
  { label: "AI-generated threat explanations", values: [false, false, true, true] },
  { label: "Custom thresholds", values: [false, false, true, true] },
  { label: "Dedicated onboarding", values: [false, false, true, true] },
  { label: "Quarterly business review", values: [false, false, true, true] },
  { label: "Multi-region support", values: [false, false, false, true] },
  { label: "Custom integrations", values: [false, false, false, true] },
  { label: "SLA guarantee", values: [false, false, false, true] },
  { label: "Dedicated infrastructure", values: [false, false, false, true] },
];
