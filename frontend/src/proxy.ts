import { NextRequest, NextResponse } from "next/server";
import { jwtVerify } from "jose";

// Server-side only. The browser reaches the API same-origin at /api (nginx in production).
const API_INTERNAL_URL = (process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
const DASHBOARD_HOST   = (process.env.DASHBOARD_HOST ?? "dashboard.localhost:3000").toLowerCase();
const DASHBOARD_URL    = (process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "http://dashboard.localhost:3000").replace(/\/+$/, "");
const HOME_URL         = (process.env.HOME_URL ?? "http://localhost:3000").replace(/\/+$/, "");
// Phase 6 staff ops panel. Pages under /internal are served only on this host.
const INTERNAL_HOST    = (process.env.INTERNAL_HOST ?? "internal.localhost:3000").toLowerCase();

const AUTH_PAGES         = ["/login", "/register", "/verify-email", "/forgot-password", "/reset-password"];
const OPEN_PAGES         = ["/accept-invite"];
const MARKETING_PREFIXES = ["/pricing", "/docs", "/legal", "/newsletter"];

const IS_DEV = process.env.NODE_ENV !== "production";

/**
 * Content Security Policy, one fresh nonce per request (Phase 10). Next.js reads
 * the nonce from the request's CSP header and stamps it on its own scripts, so
 * the policy needs no 'unsafe-inline' for scripts. 'strict-dynamic' lets those
 * trusted scripts load Razorpay Checkout and Turnstile; the host lists are only
 * the fallback for browsers that ignore strict-dynamic. 'unsafe-eval' is dev
 * only (React debugging). style-src keeps 'unsafe-inline': React inline style
 * attributes cannot carry a nonce.
 *
 * The internal (staff) host gets the strict variant: no third party at all.
 */
function buildCsp(nonce: string, internal: boolean): string {
  const thirdPartyScripts = internal ? "" : " https://challenges.cloudflare.com https://checkout.razorpay.com";
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${thirdPartyScripts}${IS_DEV ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    internal ? "img-src 'self' data:" : "img-src 'self' data: https:",
    "font-src 'self' data:",
    internal
      ? `connect-src 'self'${IS_DEV ? " ws: wss:" : ""}`
      : `connect-src 'self' https://challenges.cloudflare.com https://*.razorpay.com${IS_DEV ? " ws: wss:" : ""}`,
    internal ? "" : "frame-src https://challenges.cloudflare.com https://*.razorpay.com",
    internal ? "frame-ancestors 'none'" : "frame-ancestors 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ];
  return directives.filter(Boolean).join("; ");
}

/** Passed to every response that renders a page, so Next.js sees the nonce. */
type NonceInit = { request: { headers: Headers } };

function pathIs(pathname: string, base: string): boolean {
  return pathname === base || pathname.startsWith(`${base}/`);
}

/** Absolute URL on the host the request arrived on (nginx sets Host and X-Forwarded-Proto). */
function selfUrl(request: NextRequest, path: string): URL {
  const proto = request.headers.get("x-forwarded-proto")?.split(",")[0].trim()
    ?? request.nextUrl.protocol.replace(":", "");
  const host = request.headers.get("host") ?? request.nextUrl.host;
  return new URL(path, `${proto}://${host}`);
}

async function verifyAccessToken(token: string): Promise<boolean> {
  const raw = process.env.JWT_SECRET;
  if (!raw) return false;
  try {
    const { payload } = await jwtVerify(
      token,
      new TextEncoder().encode(raw),
      { algorithms: ["HS256"] },
    );
    return payload["type"] === "access";
  } catch {
    return false;
  }
}

/**
 * Call POST /auth/refresh with the refresh_token cookie.
 * Returns the FastAPI response if the token was rotated, null otherwise.
 */
async function tryRefresh(refreshToken: string): Promise<Response | null> {
  try {
    const res = await fetch(`${API_INTERNAL_URL}/auth/refresh`, {
      method: "POST",
      // Forward the raw cookie value; path restriction is browser-enforced only.
      headers: { Cookie: `refresh_token=${refreshToken}` },
    });
    return res.ok ? res : null;
  } catch {
    return null;
  }
}

function dashboardRewrite(request: NextRequest, init: NonceInit): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = url.pathname === "/" ? "/dashboard" : `/dashboard${url.pathname}`;
  return NextResponse.rewrite(url, init);
}

/**
 * Staff session check for the internal host. The staff token is signed with a key
 * derived from JWT_SECRET (see api/staff_auth.py), so a customer access token
 * never verifies here. This is only the edge gate: FastAPI re-checks every call.
 */
async function verifyStaffToken(token: string): Promise<boolean> {
  const raw = process.env.JWT_SECRET;
  if (!raw) return false;
  try {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`clew-staff:${raw}`));
    const key = Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
    const { payload } = await jwtVerify(token, new TextEncoder().encode(key), { algorithms: ["HS256"] });
    return payload["type"] === "staff_access";
  } catch {
    return false;
  }
}

async function internalHost(request: NextRequest, init: NonceInit): Promise<NextResponse> {
  const { pathname, search } = request.nextUrl;
  if (pathIs(pathname, "/internal")) {
    const stripped = pathname.slice("/internal".length) || "/";
    return NextResponse.redirect(selfUrl(request, `${stripped}${search}`), 308);
  }
  const token  = request.cookies.get("clew_staff")?.value;
  const authed = token ? await verifyStaffToken(token) : false;
  const rewrite = () => {
    const url = request.nextUrl.clone();
    url.pathname = pathname === "/" ? "/internal" : `/internal${pathname}`;
    return NextResponse.rewrite(url, init);
  };
  if (pathname === "/login") {
    return authed ? NextResponse.redirect(selfUrl(request, "/"), 307) : rewrite();
  }
  if (!authed) return NextResponse.redirect(selfUrl(request, "/login"), 307);
  return rewrite();
}

export async function proxy(request: NextRequest) {
  const host = (request.headers.get("host") ?? "").toLowerCase();
  const nonce = btoa(crypto.randomUUID());
  const csp = buildCsp(nonce, host === INTERNAL_HOST);

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("Content-Security-Policy", csp);
  requestHeaders.set("x-nonce", nonce);

  const response = await route(request, host, { request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

async function route(request: NextRequest, host: string, init: NonceInit): Promise<NextResponse> {
  const { pathname, search } = request.nextUrl;

  if (host === INTERNAL_HOST) return internalHost(request, init);
  // The staff panel does not exist on any other host.
  if (pathIs(pathname, "/internal")) return new NextResponse("Not found", { status: 404 });

  // Marketing host: the app lives on the dashboard host.
  if (host !== DASHBOARD_HOST) {
    if (AUTH_PAGES.includes(pathname) || OPEN_PAGES.includes(pathname)) {
      return NextResponse.redirect(new URL(`${pathname}${search}`, DASHBOARD_URL), 307);
    }
    if (pathIs(pathname, "/dashboard")) {
      const stripped = pathname.slice("/dashboard".length) || "/";
      return NextResponse.redirect(new URL(`${stripped}${search}`, DASHBOARD_URL), 307);
    }
    return NextResponse.next(init);
  }

  // Dashboard host: old /dashboard-prefixed URLs (bookmarks, emails) lose the prefix.
  if (pathIs(pathname, "/dashboard")) {
    const stripped = pathname.slice("/dashboard".length) || "/";
    return NextResponse.redirect(selfUrl(request, `${stripped}${search}`), 308);
  }

  if (MARKETING_PREFIXES.some((p) => pathIs(pathname, p))) {
    return NextResponse.redirect(new URL(`${pathname}${search}`, HOME_URL), 307);
  }

  if (OPEN_PAGES.includes(pathname)) return NextResponse.next(init);

  const isAuthPage   = AUTH_PAGES.includes(pathname);
  const accessToken  = request.cookies.get("access_token")?.value;
  const refreshToken = request.cookies.get("refresh_token")?.value;
  const valid        = accessToken ? await verifyAccessToken(accessToken) : false;

  // Authed user hitting an auth page goes to the app.
  if (isAuthPage && valid) {
    return NextResponse.redirect(selfUrl(request, "/"), 307);
  }
  if (isAuthPage) return NextResponse.next(init);

  // Everything else on this host is protected.
  if (valid) return dashboardRewrite(request, init);

  if (refreshToken) {
    const refreshRes = await tryRefresh(refreshToken);
    if (refreshRes) {
      // Forward the Set-Cookie headers FastAPI returned (new access + refresh tokens)
      const response = dashboardRewrite(request, init);
      const setCookies: string[] =
        typeof (refreshRes.headers as unknown as { getSetCookie?: () => string[] }).getSetCookie === "function"
          ? (refreshRes.headers as unknown as { getSetCookie: () => string[] }).getSetCookie()
          : refreshRes.headers.get("set-cookie")
            ? [refreshRes.headers.get("set-cookie")!]
            : [];
      for (const c of setCookies) {
        response.headers.append("set-cookie", c);
      }
      return response;
    }
  }

  // Refresh failed: redirect to login and clear stale cookies.
  const loginUrl = selfUrl(request, "/login");
  if (pathname !== "/") loginUrl.searchParams.set("next", pathname);
  const redirect = NextResponse.redirect(loginUrl, 307);
  redirect.cookies.delete("access_token");
  redirect.cookies.delete("refresh_token");
  return redirect;
}

export const config = {
  // Everything except Next internals, /api and files with an extension.
  matcher: ["/((?!api/|api$|_next/|.*\\..*).*)"],
};
