export function Footer() {
  return (
    <footer
      style={{
        borderTop: "1px solid var(--color-border)",
        padding: "32px 0",
        marginTop: "auto",
      }}
    >
      <div
        style={{ maxWidth: "1400px", margin: "0 auto", padding: "0 24px" }}
        className="flex items-center justify-between"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/clew-wordmark-dark.svg"
          alt="Clew"
          style={{ height: "14px", width: "auto", opacity: 0.4, filter: "var(--logo-filter)" }}
        />
        <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
          © {new Date().getFullYear()} Clew. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
