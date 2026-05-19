import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  const base = process.env.NEXT_PUBLIC_SITE_URL ?? "https://clewsec.com";

  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/pricing", "/register", "/login"],
        disallow: ["/dashboard/", "/api/"],
      },
    ],
    sitemap: `${base}/sitemap.xml`,
  };
}
