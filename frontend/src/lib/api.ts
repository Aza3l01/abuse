/**
 * Base URL for all FastAPI calls.
 *
 * Set NEXT_PUBLIC_API_URL in frontend/.env.local.
 * Local dev default: http://localhost:8000
 * Production:        https://api.clewsec.com
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SESSION_EXPIRED_EVENT = "clew:session-expired";

// Once a refresh attempt has failed, the session is unrecoverable until the
// user signs in again. Without this latch, every independent poller that
// calls apiFetch (the onboarding panel, dashboard summaries, etc.) kept
// retrying its own GET -> 401 -> POST /auth/refresh -> 401 cycle forever in
// a tab nobody closed, instead of backing off once the result is already
// known. Call resetSessionExpired() right before navigating back to /login,
// since Next's client-side routing keeps this module (and its state) alive
// across that navigation, a plain reload isn't guaranteed to happen.
let sessionExpired = false;

function notifySessionExpired() {
  sessionExpired = true;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
}

/** Clears the "give up" latch so a freshly-authenticated session's requests
 * actually go out again, call before/after sending the user back to /login. */
export function resetSessionExpired(): void {
  sessionExpired = false;
}

/** Subscribe to session-expiry notifications. Returns an unsubscribe function. */
export function onSessionExpired(callback: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(SESSION_EXPIRED_EVENT, callback);
  return () => window.removeEventListener(SESSION_EXPIRED_EVENT, callback);
}

/**
 * Item 14 — central API client for authenticated dashboard calls.
 *
 * On a 401: attempts a silent refresh via POST /auth/refresh, then retries
 * the original request once. If the refresh fails (or the retry still 401s),
 * emits a session-expired event (see SessionExpiredModal) and returns the
 * original response so callers' existing `if (!res.ok)` handling still works.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const url = path.startsWith("http") ? path : `${API_URL}${path}`;
  const opts: RequestInit = { credentials: "include", ...init };

  if (sessionExpired) {
    return new Response(null, { status: 401, statusText: "Session expired" });
  }

  const res = await fetch(url, opts);
  if (res.status !== 401) return res;

  const refreshRes = await fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (refreshRes.ok) {
    const retryRes = await fetch(url, opts);
    if (retryRes.status !== 401) return retryRes;
  }
  notifySessionExpired();
  return res;
}
