import { NextRequest, NextResponse } from "next/server";
import { jwtVerify } from "jose";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const PROTECTED  = ["/dashboard"];
const AUTH_PAGES = ["/login", "/register", "/verify-email", "/forgot-password", "/reset-password"];

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
    const res = await fetch(`${API_URL}/auth/refresh`, {
      method: "POST",
      // Forward the raw cookie value; path restriction is browser-enforced only.
      headers: { Cookie: `refresh_token=${refreshToken}` },
    });
    return res.ok ? res : null;
  } catch {
    return null;
  }
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isProtected = PROTECTED.some((p) => pathname.startsWith(p));
  const isAuthPage  = AUTH_PAGES.includes(pathname);

  if (!isProtected && !isAuthPage) return NextResponse.next();

  const accessToken  = request.cookies.get("access_token")?.value;
  const refreshToken = request.cookies.get("refresh_token")?.value;
  const valid        = accessToken ? await verifyAccessToken(accessToken) : false;

  // ── Authed user hitting an auth page → push to dashboard ──────────────────
  if (isAuthPage && valid) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  // ── Unauthenticated request to a protected route ──────────────────────────
  if (isProtected && !valid) {
    if (refreshToken) {
      const refreshRes = await tryRefresh(refreshToken);
      if (refreshRes) {
        // Forward the Set-Cookie headers FastAPI returned (new access + refresh tokens)
        const response = NextResponse.next();
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

    // Refresh failed — redirect to login and clear stale cookies.
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    const redirect = NextResponse.redirect(loginUrl);
    redirect.cookies.delete("access_token");
    redirect.cookies.delete("refresh_token");
    return redirect;
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/login",
    "/register",
    "/verify-email",
    "/forgot-password",
    "/reset-password",
  ],
};
