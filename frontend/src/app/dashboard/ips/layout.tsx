import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "IP Intelligence",
};

export default function IpsLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
