/**
 * Phase 4c: a tiny window-event bus so a "Guided onboarding" button living
 * on a different page than the modal (dashboard overview's empty state,
 * settings' persistent entry point) can force it open. Mirrors the
 * session-expired event pattern already used in lib/api.ts.
 */

const OPEN_ONBOARDING_EVENT = "clew:open-onboarding";

export function requestOnboardingOpen() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(OPEN_ONBOARDING_EVENT));
  }
}

/** Subscribe to onboarding-open requests. Returns an unsubscribe function. */
export function onOnboardingOpenRequested(callback: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(OPEN_ONBOARDING_EVENT, callback);
  return () => window.removeEventListener(OPEN_ONBOARDING_EVENT, callback);
}

// ---------------------------------------------------------------------------
// Docked panel width: lets the onboarding panel (mounted once, globally)
// tell the dashboard content column how much right-margin to reserve, so
// the panel can dock at the side without covering the page underneath it.
// Same window-event approach as above, just carrying a number payload.
// ---------------------------------------------------------------------------

const PANEL_WIDTH_EVENT = "clew:onboarding-panel-width";

export function setOnboardingPanelWidth(px: number) {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(PANEL_WIDTH_EVENT, { detail: px }));
  }
}

/** Subscribe to panel-width changes. Returns an unsubscribe function. */
export function onOnboardingPanelWidthChanged(callback: (px: number) => void): () => void {
  if (typeof window === "undefined") return () => {};
  const handler = (e: Event) => callback((e as CustomEvent<number>).detail);
  window.addEventListener(PANEL_WIDTH_EVENT, handler);
  return () => window.removeEventListener(PANEL_WIDTH_EVENT, handler);
}
