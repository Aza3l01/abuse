"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";

interface LegalLayoutProps {
  title: string;
  lastUpdated: string;
  children: ReactNode;
}

interface TocEntry {
  id: string;
  text: string;
  level: 2 | 3;
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * Item 12b — shared plain-content + sticky left TOC layout for all
 * /legal/* pages. Each page just supplies its own h2/h3 headings; the TOC
 * and scroll-spy highlighting are generated here, once, from the DOM.
 */
export function LegalLayout({ title, lastUpdated, children }: LegalLayoutProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [toc, setToc] = useState<TocEntry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    const container = contentRef.current;
    if (!container) return;

    const headings = Array.from(container.querySelectorAll("h2, h3")) as HTMLElement[];
    const entries: TocEntry[] = headings.map((el) => {
      if (!el.id) el.id = slugify(el.textContent ?? "");
      return { id: el.id, text: el.textContent ?? "", level: el.tagName === "H3" ? 3 : 2 };
    });
    setToc(entries);
    setActiveId(entries[0]?.id ?? null);

    if (headings.length === 0) return;
    const observer = new IntersectionObserver(
      (observed) => {
        const visible = observed.filter((e) => e.isIntersecting);
        if (visible.length > 0) setActiveId(visible[0].target.id);
      },
      { rootMargin: "0px 0px -70% 0px", threshold: 0 }
    );
    headings.forEach((h) => observer.observe(h));
    return () => observer.disconnect();
  }, [children]);

  return (
    <div
      className="flex flex-col min-h-screen"
      style={{ background: "var(--color-bg)", color: "var(--color-text)" }}
    >
      <Navbar />
      <main className="flex-1" style={{ padding: "48px 24px" }}>
        <div style={{ maxWidth: "1080px", margin: "0 auto", display: "flex", gap: "48px", alignItems: "flex-start" }}>
          {toc.length > 0 && (
            <aside
              className="hidden lg:block"
              style={{
                width: "220px",
                flexShrink: 0,
                position: "sticky",
                top: "96px",
                borderRight: "1px solid var(--color-border)",
                paddingRight: "24px",
              }}
            >
              <p
                style={{
                  fontSize: "11px",
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.07em",
                  color: "var(--color-text-muted)",
                  marginBottom: "12px",
                }}
              >
                On this page
              </p>
              <nav style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                {toc.map((entry) => (
                  <a
                    key={entry.id}
                    href={`#${entry.id}`}
                    style={{
                      fontSize: "13px",
                      padding: "4px 0 4px 12px",
                      marginLeft: entry.level === 3 ? "12px" : "0",
                      borderLeft: `1px solid ${activeId === entry.id ? "var(--color-text)" : "var(--color-border)"}`,
                      color: activeId === entry.id ? "var(--color-text)" : "var(--color-text-muted)",
                      textDecoration: "none",
                      transition: "color 150ms, border-color 150ms",
                    }}
                  >
                    {entry.text}
                  </a>
                ))}
              </nav>
            </aside>
          )}

          <article style={{ maxWidth: "720px", flex: 1, minWidth: 0 }}>
            <h1
              style={{
                fontFamily: "var(--font-brand)",
                fontSize: "28px",
                fontWeight: 700,
                marginBottom: "8px",
              }}
            >
              {title}
            </h1>
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "40px" }}>
              Last updated: {lastUpdated}
            </p>
            <div ref={contentRef} style={{ fontSize: "14px", lineHeight: 1.7, color: "var(--color-text)" }}>
              {children}
            </div>
          </article>
        </div>
      </main>
      <Footer />
    </div>
  );
}

export const legalH2Style: React.CSSProperties = {
  fontSize: "18px",
  fontWeight: 700,
  marginTop: "32px",
  marginBottom: "12px",
};

export const legalPStyle: React.CSSProperties = {
  marginBottom: "16px",
};
