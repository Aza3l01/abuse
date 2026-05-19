import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Create your account",
  description: "Get started with Clew — API abuse detection and blocking for growing SaaS companies. Free tier available.",
};

export default function RegisterLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
