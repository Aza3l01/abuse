// Client helpers for the internal ops panel (Phase 6). Staff only: these calls
// go to /internal/* on the internal host and carry the clew_staff cookie, never
// the customer session. A 401 sends the browser to the staff login page.
import { API_URL } from "@/lib/api";

export class StaffApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function staffRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}/internal${path}`, {
    credentials: "include",
    cache: "no-store",
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  if (res.status === 401 && path !== "/auth/login") {
    if (typeof window !== "undefined") window.location.assign("/login");
    throw new StaffApiError(401, "Session expired.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : "Request failed.";
    throw new StaffApiError(res.status, detail);
  }
  return data as T;
}

export function staffPost<T>(path: string, body: unknown): Promise<T> {
  return staffRequest<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export const CSV_EXPORT_URL = `${API_URL}/internal/metrics/export.csv`;

export type Cell = string | number | boolean | null;
export type Row = Record<string, Cell>;
export type Kv = Record<string, Cell>;

export interface OrgSummary {
  id: string;
  company_name: string;
  tier: string;
  billing_provider: string | null;
  owner_email: string | null;
  created_at: string | null;
  deleted: boolean;
}

export interface AccountView {
  org: Kv;
  onboarding: Kv;
  usage: Kv;
  scan: Kv;
  billing: Kv;
  trial: Kv;
  referral: Kv;
  members: Row[];
  bills: Row[];
  payments: Row[];
  events: Row[];
  audit: Row[];
  as_of: string;
}

export interface HealthView {
  tasks: Row[];
  task_runs_recorded: boolean;
  /** Latest Razorpay vs local payment check, or null if it has not run yet. */
  reconciliation: {
    ran_at: string;
    window_start: string;
    checked: number;
    discrepancies: Row[];
  } | null;
  recent_webhook_events: Row[];
  failed_payments: Row[];
  stuck_payments: Row[];
  llm_usage: Row[];
}

export interface MetricsView {
  as_of: string;
  headline_currency: string;
  /** INR per 1 USD as plain text: the rate entered on the page, else METRICS_INR_PER_USD, else null. */
  rate: string | null;
  rate_source: "entered" | "server" | null;
  current: Row[];
  history: Row[];
  /** Combined INR row, or a row with only a null inr_per_usd when the rate is not set. */
  combined_current: Row | null;
  combined_history: Row[];
}

/** Minor units as a decimal in major units with the currency code, per row (the per-currency rows are never altered). */
export function formatMinor(minor: Cell | undefined, currency: Cell | undefined): string {
  if (typeof minor !== "number") return "-";
  const sign = minor < 0 ? "-" : "";
  const abs = Math.abs(minor);
  const whole = Math.trunc(abs / 100);
  const frac = String(abs % 100).padStart(2, "0");
  return `${sign}${whole}.${frac} ${typeof currency === "string" ? currency : ""}`.trim();
}

const ISO_TIMESTAMP = /^\d{4}-\d\d-\d\dT\d\d:\d\d/;

export function formatCell(value: Cell | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string" && ISO_TIMESTAMP.test(value)) {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) {
      const iso = parsed.toISOString();
      return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
    }
  }
  return String(value);
}
