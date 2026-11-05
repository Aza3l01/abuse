// Absolute URLs for links that cross between the marketing and dashboard hosts.
// Both values are baked at build time (NEXT_PUBLIC_*), so set them before `next build`.
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/+$/, "");
export const DASHBOARD_URL = (process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "http://dashboard.localhost:3000").replace(/\/+$/, "");
