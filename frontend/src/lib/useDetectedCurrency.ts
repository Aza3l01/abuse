"use client";

import { useState, useSyncExternalStore } from "react";

export type DisplayCurrency = "INR" | "USD";

function subscribeNever() {
  return () => {};
}

function detectCurrency(): DisplayCurrency {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const lang = navigator.language || "";
  const isIndia =
    tz.includes("Kolkata") ||
    tz.includes("Calcutta") ||
    lang === "hi" ||
    lang.endsWith("-IN");
  return isIndia ? "INR" : "USD";
}

/**
 * Display currency guessed from the visitor's timezone and language, with a
 * manual override. The server render and first client render use INR, then the
 * detected value takes over, so hydration stays consistent.
 */
export function useDetectedCurrency(): [DisplayCurrency, (c: DisplayCurrency) => void] {
  const detected = useSyncExternalStore<DisplayCurrency>(subscribeNever, detectCurrency, () => "INR");
  const [override, setOverride] = useState<DisplayCurrency | null>(null);
  return [override ?? detected, setOverride];
}
