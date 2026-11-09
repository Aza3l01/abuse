"use client";

import { useSyncExternalStore } from "react";

const MOBILE_BREAKPOINT = "(max-width: 768px)";

/** Height (px) of the mobile top bar that replaces the sidebar below the
 * breakpoint. Dashboard pages need this to offset their own top padding. */
export const MOBILE_TOPBAR_HEIGHT = 52;

function subscribe(onChange: () => void) {
  const mql = window.matchMedia(MOBILE_BREAKPOINT);
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

/**
 * True when the viewport matches the dashboard's mobile breakpoint.
 * Reports false (desktop layout) during SSR and hydration, since there's no
 * viewport to read there, then follows resize/orientation changes.
 */
export function useIsMobile(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(MOBILE_BREAKPOINT).matches,
    () => false,
  );
}
