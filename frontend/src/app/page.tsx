import type { Metadata } from "next";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import { Hero } from "@/components/home/Hero";
import { CostCalculator } from "@/components/home/CostCalculator";
import { HowItWorks } from "@/components/home/HowItWorks";
import { AgentsSection } from "@/components/home/AgentsSection";
import { Pricing } from "@/components/home/Pricing";

export const metadata: Metadata = {
  title: { absolute: "Clew" },
  description:
    "Seven specialised AI agents monitor your AWS API Gateway logs for bots, credential stuffing, scrapers, and data exfiltration. No code changes. No proxy. Just connect your S3 logs.",
};

export default function Home() {
  return (
    <div
      className="flex flex-col min-h-screen"
      style={{ background: "var(--color-bg)", color: "var(--color-text)" }}
    >
      <Navbar />
      <main className="flex-1">
        <Hero />
        <CostCalculator />
        <HowItWorks />
        <AgentsSection />
        <Pricing />
      </main>
      <Footer />
    </div>
  );
}
