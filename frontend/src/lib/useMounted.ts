"use client";

import { useSyncExternalStore } from "react";

function subscribeNever() {
  return () => {};
}

/** False during SSR and hydration, true once running in the browser. */
export function useMounted(): boolean {
  return useSyncExternalStore(subscribeNever, () => true, () => false);
}
