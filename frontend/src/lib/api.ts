/**
 * Base URL for all FastAPI calls.
 *
 * Set NEXT_PUBLIC_API_URL in frontend/.env.local.
 * Local dev default: http://localhost:8000
 * Production:        https://api.clewsec.com
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SESSION_EXPIRED_EVENT = "clew:session-expired";

function notifySessionExpired() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
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
