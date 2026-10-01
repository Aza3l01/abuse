"use client";

import { useEffect, useState } from "react";

const MOBILE_BREAKPOINT = "(max-width: 768px)";

/** Height (px) of the mobile top bar that replaces the sidebar below the
 * breakpoint. Dashboard pages need this to offset their own top padding. */
export const MOBILE_TOPBAR_HEIGHT = 52;

/**
 * True when the viewport matches the dashboard's mobile breakpoint.
 * Starts false (desktop layout) until mounted, since there's no viewport to
 * read during SSR, then updates on mount and on resize/orientation change.
 */
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(MOBILE_BREAKPOINT);
    setIsMobile(mql.matches);
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return isMobile;
}
