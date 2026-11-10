// Phase 11: PostHog (EU), loaded only after the visitor accepts the consent
// banner. Nothing here runs, and posthog-js is not even downloaded, until
// consent is "granted". Everything is a no-op when NEXT_PUBLIC_POSTHOG_KEY is
// blank, which is the local default.
//
// What is deliberately off: autocapture (it would send dashboard text such as
// customer IPs), session replay, heatmaps, dead clicks, surveys, feature flags.
// URLs are scrubbed in before_send so a token in a query string never leaves
// the browser.
import type { CaptureResult, PostHog } from "posthog-js";

const POSTHOG_KEY  = process.env.NEXT_PUBLIC_POSTHOG_KEY ?? "";
const POSTHOG_HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://eu.i.posthog.com";
// Shared by the marketing and dashboard hosts so one choice covers both,
// for example ".clewsec.com". Blank in dev: the cookies stay host-only.
const COOKIE_DOMAIN = process.env.NEXT_PUBLIC_COOKIE_DOMAIN ?? "";

export const analyticsConfigured = POSTHOG_KEY !== "";

export const CONSENT_COOKIE = "clew_consent";
export const OPEN_CONSENT_EVENT = "clew:open-consent";
const CONSENT_CHANGED_EVENT = "clew:consent-changed";
const CONSENT_MAX_AGE_SECONDS = 60 * 60 * 24 * 180;

export type Consent = "granted" | "denied";

// Pages whose URL carries a one-time token. No pageview is ever sent for them.
const NO_EVENT_PATHS = ["/accept-invite", "/reset-password", "/verify-email"];
const KEEP_PARAMS = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"];
const URL_KEYS = ["$current_url", "$referrer", "$initial_referrer", "$initial_current_url"];
const PATH_KEYS = ["$pathname", "$initial_pathname"];

// --- consent cookie ----------------------------------------------------------

export function readConsent(): Consent | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${CONSENT_COOKIE}=`));
  const value = match?.slice(CONSENT_COOKIE.length + 1);
  return value === "granted" || value === "denied" ? value : null;
}

function cookieAttributes(maxAge: number): string {
  const parts = ["Path=/", `Max-Age=${maxAge}`, "SameSite=Lax"];
  if (COOKIE_DOMAIN) parts.push(`Domain=${COOKIE_DOMAIN}`);
  if (window.location.protocol === "https:") parts.push("Secure");
  return parts.join("; ");
}

export function writeConsent(value: Consent): void {
  document.cookie = `${CONSENT_COOKIE}=${value}; ${cookieAttributes(CONSENT_MAX_AGE_SECONDS)}`;
  window.dispatchEvent(new Event(CONSENT_CHANGED_EVENT));
}

/** Subscribe to consent changes made by writeConsent. Returns an unsubscribe function. */
export function onConsentChange(callback: () => void): () => void {
  window.addEventListener(CONSENT_CHANGED_EVENT, callback);
  return () => window.removeEventListener(CONSENT_CHANGED_EVENT, callback);
}

// --- URL scrubbing -----------------------------------------------------------

/** Replaces id segments so a pageview never carries a record id. */
export function genericPath(pathname: string): string {
  return pathname
    .replace(/^(\/dashboard)?\/verdicts\/[^/]+/, "$1/verdicts/:id")
    .replace(/^(\/dashboard)?\/billing\/receipt\/[^/]+/, "$1/billing/receipt/:id");
}

/** Drops the hash and every query parameter except the utm_* campaign ones. */
export function sanitizeUrl(raw: string): string {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return raw; // not a URL, for example "$direct"
  }
  url.pathname = genericPath(url.pathname);
  url.hash = "";
  for (const key of Array.from(url.searchParams.keys())) {
    if (!KEEP_PARAMS.includes(key)) url.searchParams.delete(key);
  }
  return url.toString();
}

function isTokenPage(rawUrl: unknown): boolean {
  if (typeof rawUrl !== "string") return false;
  try {
    return NO_EVENT_PATHS.includes(new URL(rawUrl).pathname);
  } catch {
    return false;
  }
}

function scrub(cr: CaptureResult | null): CaptureResult | null {
  if (!cr) return cr;
  if ((cr.event === "$pageview" || cr.event === "$pageleave") && isTokenPage(cr.properties?.["$current_url"])) {
    return null;
  }
  for (const bag of [cr.properties, cr.$set, cr.$set_once]) {
    if (!bag) continue;
    for (const key of URL_KEYS) {
      if (typeof bag[key] === "string") bag[key] = sanitizeUrl(bag[key]);
    }
    for (const key of PATH_KEYS) {
      if (typeof bag[key] === "string") bag[key] = genericPath(bag[key]);
    }
  }
  return cr;
}

// --- client ------------------------------------------------------------------

let client: PostHog | null = null;
let loading = false;
let pendingIdentify: string | null = null;
const queue: Array<(ph: PostHog) => void> = [];
const MAX_QUEUE = 20;

function applyPending(ph: PostHog): void {
  if (pendingIdentify) ph.identify(pendingIdentify);
  pendingIdentify = null;
  for (const fn of queue.splice(0)) fn(ph);
}

/** Call once consent is "granted". Safe to call repeatedly. */
export function startAnalytics(): void {
  if (!analyticsConfigured || typeof window === "undefined") return;
  if (client) {
    if (client.has_opted_out_capturing()) client.opt_in_capturing({ captureEventName: false });
    applyPending(client);
    return;
  }
  if (loading) return;
  loading = true;
  import("posthog-js")
    .then(({ default: posthog }) => {
      posthog.init(POSTHOG_KEY, {
        api_host: POSTHOG_HOST,
        ui_host: "https://eu.posthog.com",
        persistence: "cookie",
        cross_subdomain_cookie: COOKIE_DOMAIN !== "",
        secure_cookie: window.location.protocol === "https:",
        autocapture: false,
        capture_pageview: "history_change",
        capture_pageleave: true,
        capture_dead_clicks: false,
        capture_heatmaps: false,
        capture_exceptions: true,
        disable_session_recording: true,
        disable_surveys: true,
        advanced_disable_flags: true,
        person_profiles: "identified_only",
        before_send: scrub,
      });
      if (posthog.has_opted_out_capturing()) posthog.opt_in_capturing({ captureEventName: false });
      client = posthog;
      applyPending(posthog);
    })
    .catch(() => {
      // Blocked or offline: analytics is best effort, never break the page.
    })
    .finally(() => {
      loading = false;
    });
}

/** Call when consent is withdrawn: stop capturing and drop PostHog's cookies. */
export function stopAnalytics(): void {
  queue.length = 0;
  pendingIdentify = null;
  if (!client) return;
  client.opt_out_capturing();
  client.reset();
  for (const cookie of document.cookie.split("; ")) {
    const name = cookie.split("=")[0];
    if (!name.startsWith("ph_")) continue;
    document.cookie = `${name}=; ${cookieAttributes(0)}`;
    document.cookie = `${name}=; Path=/; Max-Age=0`;
  }
}

function run(fn: (ph: PostHog) => void): void {
  if (client) {
    fn(client);
    return;
  }
  if (readConsent() === "granted" && queue.length < MAX_QUEUE) queue.push(fn);
}

/** Send a funnel event. Dropped silently without consent. */
export function track(event: string, properties?: Record<string, string | number | boolean | null>): void {
  run((ph) => ph.capture(event, properties));
}

/** Link this browser to the client UUID, the same id the backend events use. */
export function identifyUser(clientId: string): void {
  if (client) {
    if (!client.has_opted_out_capturing()) client.identify(clientId);
  } else {
    pendingIdentify = clientId;
  }
}

export function captureError(error: unknown): void {
  run((ph) => ph.captureException(error));
}

/**
 * Funnel step "S3 connection completed". Call with the connection status from
 * before a save and the saved config, so only the move into "connected" counts
 * (a later re-save of an already connected org does not).
 */
export function trackS3Connected(
  previousStatus: string | null | undefined,
  saved: { s3_status: string | null; log_format: string | null },
): void {
  if (saved.s3_status === "connected" && previousStatus !== "connected") {
    track("s3_connected", { log_format: saved.log_format });
  }
}
