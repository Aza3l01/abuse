"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import Script from "next/script";

declare global {
  interface Window {
    turnstile?: {
      render: (
        container: HTMLElement,
        options: {
          sitekey: string;
          callback: (token: string) => void;
          "expired-callback"?: () => void;
        }
      ) => string;
      remove: (widgetId: string) => void;
      reset: (widgetId: string) => void;
    };
  }
}

interface TurnstileProps {
  onToken: (token: string) => void;
}

/** What a parent can call through a ref. */
export interface TurnstileHandle {
  /** Clears the token and asks Cloudflare for a fresh challenge. A token is
   *  single use, so call this after every request that sent one and failed. */
  reset: () => void;
}

/** Cloudflare Turnstile CAPTCHA widget. Item 10/38. */
export const Turnstile = forwardRef<TurnstileHandle, TurnstileProps>(function Turnstile({ onToken }, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [scriptLoaded, setScriptLoaded] = useState(false);
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";

  useImperativeHandle(ref, () => ({
    reset() {
      onToken("");
      if (widgetIdRef.current !== null) window.turnstile?.reset(widgetIdRef.current);
    },
  }));

  useEffect(() => {
    if (!scriptLoaded || !containerRef.current || !window.turnstile) return;
    const widgetId = window.turnstile.render(containerRef.current, {
      sitekey: siteKey,
      callback: onToken,
      "expired-callback": () => onToken(""),
    });
    widgetIdRef.current = widgetId;
    // Remove the widget on unmount so leaving and re-entering the page does
    // not leave an orphaned widget behind in Turnstile's own state.
    return () => {
      widgetIdRef.current = null;
      window.turnstile?.remove(widgetId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptLoaded]);

  return (
    <>
      <Script
        src="https://challenges.cloudflare.com/turnstile/v0/api.js"
        strategy="afterInteractive"
        onReady={() => setScriptLoaded(true)}
      />
      <div ref={containerRef} />
    </>
  );
});
