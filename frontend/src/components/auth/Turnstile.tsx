"use client";

import { useEffect, useRef, useState } from "react";
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
    };
  }
}

interface TurnstileProps {
  onToken: (token: string) => void;
}

/** Cloudflare Turnstile CAPTCHA widget — item 10/38. */
export function Turnstile({ onToken }: TurnstileProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scriptLoaded, setScriptLoaded] = useState(false);
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";

  useEffect(() => {
    if (scriptLoaded && containerRef.current && window.turnstile) {
      window.turnstile.render(containerRef.current, {
        sitekey: siteKey,
        callback: onToken,
        "expired-callback": () => onToken(""),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptLoaded]);

  return (
    <>
      <Script
        src="https://challenges.cloudflare.com/turnstile/v0/api.js"
        strategy="afterInteractive"
        onLoad={() => setScriptLoaded(true)}
      />
      <div ref={containerRef} />
    </>
  );
}
