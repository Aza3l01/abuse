import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Dev only. In production nginx proxies /api/ to FastAPI; a Next.js rewrite
  // would hide the client IP from the rate limiter.
  async rewrites() {
    if (process.env.NODE_ENV === "production") return [];
    const target = (process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
    return [{ source: "/api/:path*", destination: `${target}/:path*` }];
  },
};

export default nextConfig;
