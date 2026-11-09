import type { Metadata } from "next";
import type { ReactNode } from "react";
import { InternalShell } from "@/components/internal/InternalShell";

export const metadata: Metadata = {
  title: "Clew internal",
  robots: { index: false, follow: false },
};

/** Layout for every /internal/* page. Reached only on the internal host: the
 * Next.js proxy rewrites that host's paths here and 404s /internal elsewhere. */
export default function InternalLayout({ children }: { children: ReactNode }) {
  return <InternalShell>{children}</InternalShell>;
}
