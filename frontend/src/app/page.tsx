import type { Metadata } from "next";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import { Hero } from "@/components/home/Hero";
import { CostCalculator } from "@/components/home/CostCalculator";
import { HowItWorks } from "@/components/home/HowItWorks";
import { Pricing } from "@/components/home/Pricing";

export const metadata: Metadata = {
  title: "API Security for Growing SaaS",
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
        <Pricing />
      </main>
      <Footer />
    </div>
  );
}
