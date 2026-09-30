"use client";

import { useEffect, useState, type ReactNode } from "react";
import { onOnboardingPanelWidthChanged } from "@/lib/onboarding";

/**
 * Wraps dashboard page content and reserves right-margin for the docked
 * guided onboarding panel, so the panel never covers the page underneath it.
 * Width comes from OnboardingModal via a window event, 0 when the panel
 * isn't docked (hidden or minimized to its chip).
 */
export function DashboardContentShell({ children }: { children: ReactNode }) {
  const [panelWidth, setPanelWidth] = useState(0);

  useEffect(() => onOnboardingPanelWidthChanged(setPanelWidth), []);

  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        marginRight: panelWidth,
        transition: "margin-right 220ms ease",
      }}
    >
      {children}
    </div>
  );
}
