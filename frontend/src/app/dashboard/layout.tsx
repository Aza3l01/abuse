import type { Metadata } from "next";
import type { ReactNode } from "react";
import { DashboardSidebar } from "@/components/dashboard/Sidebar";
import { DashboardGate } from "@/components/dashboard/DashboardGate";
import { MfaNudgeBanner } from "@/components/dashboard/MfaNudgeBanner";
import { TrialBanner } from "@/components/dashboard/TrialBanner";
import { SessionExpiredModal } from "@/components/dashboard/SessionExpiredModal";
import { StatusHeader } from "@/components/dashboard/StatusHeader";

export const metadata: Metadata = {
  title: "Dashboard",
};

/**
 * Shared layout for all /dashboard/* pages.
 *
 * Renders the sidebar (sticky, full-height) on the left and the page
 * content on the right in a scrollable flex column. The sidebar is a
 * Client Component (needs usePathname for active-link highlighting);
 * this layout itself is a Server Component. DashboardGate blocks all of
 * this behind a "create your organisation" step if the client has none yet.
 */
export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <DashboardGate>
      <div style={{ display: "flex", minHeight: "100vh", background: "var(--color-bg)" }}>
        <DashboardSidebar />
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          <StatusHeader />
          <TrialBanner />
          <MfaNudgeBanner />
          {children}
        </div>
      </div>
      <SessionExpiredModal />
    </DashboardGate>
  );
}
