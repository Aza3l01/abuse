import type { Metadata } from "next";
import type { ReactNode } from "react";
import { DashboardSidebar } from "@/components/dashboard/Sidebar";

export const metadata: Metadata = {
  title: "Dashboard",
};

/**
 * Shared layout for all /dashboard/* pages.
 *
 * Renders the sidebar (sticky, full-height) on the left and the page
 * content on the right in a scrollable flex column. The sidebar is a
 * Client Component (needs usePathname for active-link highlighting);
 * this layout itself is a Server Component.
 */
export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--color-bg)" }}>
      <DashboardSidebar />
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        {children}
      </div>
    </div>
  );
}
