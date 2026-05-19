"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import Image from "next/image";
import { API_URL } from "@/lib/api";

function useIsLoggedIn() {
  const [loggedIn, setLoggedIn] = useState(false);
  useEffect(() => {
    fetch(`${API_URL}/auth/me`, { credentials: "include" })
      .then((r) => setLoggedIn(r.ok))
      .catch(() => setLoggedIn(false));
  }, []);
  return loggedIn;
}

export function Navbar() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const loggedIn = useIsLoggedIn();

  useEffect(() => {
    setMounted(true);
  }, []);

  // SVG is filled #f5f5f5 (light). Invert in light mode so it reads dark on light bg.
  const logoFilter = mounted && theme !== "dark" ? "invert(1)" : "none";

  return (
    <nav
      style={{
        borderBottom: "1px solid var(--color-border)",
        background: "var(--color-bg)",
      }}
    >
      <div
        style={{ maxWidth: "1400px", margin: "0 auto", padding: "0 24px" }}
        className="h-14 flex items-center justify-between"
      >
        <a href="/" aria-label="Clew home">
          <Image
            src="/clew-wordmark.svg"
            alt="Clew"
            width={72}
            height={40}
            priority
            style={{ filter: logoFilter, height: "20px", width: "auto" }}
          />
        </a>

        <div className="flex items-center gap-6">
          <a
            href="/#pricing"
            onClick={(e) => {
              if (window.location.pathname === "/") {
                const el = document.getElementById("pricing");
                if (el) { e.preventDefault(); el.scrollIntoView({ behavior: "smooth" }); }
              }
            }}
            className="text-sm transition-colors"
            style={{ color: "var(--color-text-muted)" }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.color = "var(--color-text)")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.color = "var(--color-text-muted)")
            }
          >
            Pricing
          </a>
          <a
            href={loggedIn ? "/dashboard" : "/login"}
            className="text-sm transition-colors"
            style={{ color: "var(--color-text-muted)" }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.color = "var(--color-text)")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.color = "var(--color-text-muted)")
            }
          >
            {loggedIn ? "Dashboard" : "Sign in"}
          </a>

          {mounted && (
            <button
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label="Toggle theme"
              className="w-8 h-8 flex items-center justify-center transition-colors"
              style={{
                border: "1px solid var(--color-border)",
                background: "var(--color-surface)",
                color: "var(--color-text-muted)",
              }}
            >
              {theme === "dark" ? <SunIcon /> : <MoonIcon />}
            </button>
          )}
        </div>
      </div>
    </nav>
  );
}

function SunIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="square"
    >
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="square"
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}
