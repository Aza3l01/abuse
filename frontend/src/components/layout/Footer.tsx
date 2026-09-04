import Link from "next/link";

// Every column links to a route that actually exists in this codebase —
// no Docs/Blog/Careers/Community placeholders for pages that aren't built.
const COLUMNS: { heading: string; links: { href: string; label: string; external?: boolean }[] }[] = [
  {
    heading: "Product",
    links: [
      { href: "/", label: "Home" },
      { href: "/pricing", label: "Pricing" },
    ],
  },
  {
    heading: "Account",
    links: [
      { href: "/login", label: "Login" },
      { href: "/register", label: "Register" },
    ],
  },
  {
    heading: "Legal",
    links: [
      { href: "/legal/terms", label: "Terms of Service" },
      { href: "/legal/privacy", label: "Privacy Policy" },
      { href: "/legal/dpa", label: "DPA" },
      { href: "/legal/refund-policy", label: "Refund Policy" },
      { href: "/legal/subscription-agreement", label: "Subscription Agreement" },
    ],
  },
  {
    heading: "Company",
    links: [
      { href: "mailto:jeff@clewsec.com", label: "Contact", external: true },
    ],
  },
];

const linkStyle: React.CSSProperties = {
  fontSize: "13px",
  color: "var(--color-text-muted)",
  textDecoration: "none",
  transition: "color 150ms",
};

const columnHeadingStyle: React.CSSProperties = {
  fontSize: "11px",
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.07em",
  color: "var(--color-text-muted)",
  marginBottom: "16px",
};

export function Footer() {
  return (
    <footer
      style={{
        borderTop: "1px solid var(--color-border)",
        padding: "56px 0 24px",
        marginTop: "auto",
      }}
    >
      <div style={{ maxWidth: "1400px", margin: "0 auto", padding: "0 24px" }}>
        <div
          className="flex flex-wrap justify-between"
          style={{ gap: "48px", marginBottom: "48px" }}
        >
          {/* Brand column */}
          <div style={{ maxWidth: "280px" }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/clew-wordmark-dark.svg"
              alt="Clew"
              style={{ height: "22px", width: "auto", filter: "var(--logo-filter)", marginBottom: "12px" }}
            />
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)", lineHeight: 1.5 }}>
              API abuse detection and blocking for growing SaaS companies.
            </p>
            <a
              href="https://www.linkedin.com/company/117823996"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Clew on LinkedIn"
              className="transition-opacity hover:opacity-70"
              style={{ display: "inline-flex", marginTop: "12px", color: "var(--color-text)" }}
            >
              <svg width="18" height="18" viewBox="0 0 448 512" fill="currentColor" aria-hidden="true">
                <path d="M100.28 448H7.4V149.2h92.88zm-46.44-339.7C24.09 108.3 0 84.1 0 54.3a53.79 53.79 0 0 1 107.58 0c0 29.8-24.1 54-53.79 54zM447.9 448h-92.68V302.4c0-34.7-.7-79.2-48.29-79.2-48.29 0-55.69 37.7-55.69 76.7V448h-92.78V149.2h89.08v40.8h1.3c12.4-23.5 42.69-48.3 87.88-48.3 94 0 111.28 61.9 111.28 142.3z" />
              </svg>
            </a>
          </div>

          {/* Link columns */}
          {COLUMNS.map((col) => (
            <nav key={col.heading}>
              <p style={columnHeadingStyle}>{col.heading}</p>
              <ul style={{ display: "flex", flexDirection: "column", gap: "10px", listStyle: "none", margin: 0, padding: 0 }}>
                {col.links.map((l) => (
                  <li key={l.href}>
                    {l.external ? (
                      <a href={l.href} style={linkStyle}>{l.label}</a>
                    ) : (
                      <Link href={l.href} style={linkStyle}>{l.label}</Link>
                    )}
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
      </div>

      <div style={{ borderTop: "1px solid var(--color-border)", paddingTop: "16px" }}>
        <div
          style={{ maxWidth: "1400px", margin: "0 auto", padding: "0 24px" }}
          className="flex items-center justify-between"
        >
          <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
            © {new Date().getFullYear()} Clew. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}
