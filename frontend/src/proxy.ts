import { NextRequest, NextResponse } from "next/server";
import { jwtVerify } from "jose";

// Server-side only. The browser reaches the API same-origin at /api (nginx in production).
const API_INTERNAL_URL = (process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
const DASHBOARD_HOST   = (process.env.DASHBOARD_HOST ?? "dashboard.localhost:3000").toLowerCase();
const DASHBOARD_URL    = (process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "http://dashboard.localhost:3000").replace(/\/+$/, "");
const MARKETING_URL    = (process.env.MARKETING_URL ?? "http://localhost:3000").replace(/\/+$/, "");

const AUTH_PAGES         = ["/login", "/register", "/verify-email", "/forgot-password", "/reset-password"];
const OPEN_PAGES         = ["/accept-invite"];
const MARKETING_PREFIXES = ["/pricing", "/docs", "/legal", "/newsletter"];

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

function dashboardRewrite(request: NextRequest): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = url.pathname === "/" ? "/dashboard" : `/dashboard${url.pathname}`;
  return NextResponse.rewrite(url);
}

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const host = (request.headers.get("host") ?? "").toLowerCase();

  // Marketing host: the app lives on the dashboard host.
  if (host !== DASHBOARD_HOST) {
    if (AUTH_PAGES.includes(pathname) || OPEN_PAGES.includes(pathname)) {
      return NextResponse.redirect(new URL(`${pathname}${search}`, DASHBOARD_URL), 307);
    }
    if (pathIs(pathname, "/dashboard")) {
      const stripped = pathname.slice("/dashboard".length) || "/";
      return NextResponse.redirect(new URL(`${stripped}${search}`, DASHBOARD_URL), 307);
    }
    return NextResponse.next();
  }

  // Dashboard host: old /dashboard-prefixed URLs (bookmarks, emails) lose the prefix.
  if (pathIs(pathname, "/dashboard")) {
    const stripped = pathname.slice("/dashboard".length) || "/";
    return NextResponse.redirect(selfUrl(request, `${stripped}${search}`), 308);
  }

  if (MARKETING_PREFIXES.some((p) => pathIs(pathname, p))) {
    return NextResponse.redirect(new URL(`${pathname}${search}`, MARKETING_URL), 307);
  }

  if (OPEN_PAGES.includes(pathname)) return NextResponse.next();

  const isAuthPage   = AUTH_PAGES.includes(pathname);
  const accessToken  = request.cookies.get("access_token")?.value;
  const refreshToken = request.cookies.get("refresh_token")?.value;
  const valid        = accessToken ? await verifyAccessToken(accessToken) : false;

  // Authed user hitting an auth page goes to the app.
  if (isAuthPage && valid) {
    return NextResponse.redirect(selfUrl(request, "/"), 307);
  }
  if (isAuthPage) return NextResponse.next();

  // Everything else on this host is protected.
  if (valid) return dashboardRewrite(request);

  if (refreshToken) {
    const refreshRes = await tryRefresh(refreshToken);
    if (refreshRes) {
      // Forward the Set-Cookie headers FastAPI returned (new access + refresh tokens)
      const response = dashboardRewrite(request);
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
