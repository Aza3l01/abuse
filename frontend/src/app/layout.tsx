import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Courier_Prime } from "next/font/google";
import { ThemeProvider } from "@/components/providers/ThemeProvider";
import "./globals.css";

const courierPrime = Courier_Prime({
  weight: ["400", "700"],
  subsets: ["latin"],
  variable: "--font-courier",
});

export const metadata: Metadata = {
  title: {
    default: "Clew",
    template: "%s",
  },
  description:
    "API abuse detection and blocking for growing SaaS companies. No code changes. No proxy. Just connect your S3 logs.",
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "https://clewsec.com"
  ),
  openGraph: {
    type: "website",
    siteName: "Clew",
    title: "Clew — API Abuse Detection for SaaS",
    description:
      "Detect bots, credential stuffing, scrapers, and data exfiltration in your AWS API Gateway logs. No code changes. No proxy.",
    url: process.env.NEXT_PUBLIC_SITE_URL ?? "https://clewsec.com",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "Clew — API Abuse Detection",
      },
    ],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${GeistSans.variable} ${GeistMono.variable} ${courierPrime.variable}`}
    >
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
