"use client";

import { useEffect, useState, type ReactNode } from "react";
import { onOnboardingPanelWidthChanged } from "@/lib/onboarding";
import { useIsMobile, MOBILE_TOPBAR_HEIGHT } from "@/lib/useIsMobile";

/**
 * Wraps dashboard page content and reserves right-margin for the docked
 * guided onboarding panel, so the panel never covers the page underneath it.
 * Width comes from OnboardingModal via a window event, 0 when the panel
 * isn't docked (hidden or minimized to its chip). Below the mobile
 * breakpoint the sidebar becomes a fixed top bar instead of a left column
 * (see Sidebar.tsx), so this also reserves top padding to clear it.
 */
export function DashboardContentShell({ children }: { children: ReactNode }) {
  const [panelWidth, setPanelWidth] = useState(0);
  const isMobile = useIsMobile();

  useEffect(() => onOnboardingPanelWidthChanged(setPanelWidth), []);

  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        marginRight: isMobile ? 0 : panelWidth,
        paddingTop: isMobile ? `${MOBILE_TOPBAR_HEIGHT}px` : 0,
        transition: "margin-right 220ms ease",
      }}
    >
      {children}
    </div>
  );
}
