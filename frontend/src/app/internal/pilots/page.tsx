"use client";

import { useState } from "react";
import { ErrorLine, Section, buttonStyle, inputStyle, mono } from "@/components/internal/ui";
import { StaffApiError, staffPost } from "@/lib/staffApi";

export default function PilotsPage() {
  const [count, setCount] = useState("5");
  const [reason, setReason] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function generate(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setCodes([]);
    if (!window.confirm("Generate pilot codes? This is written to the audit log.")) return;
    setBusy(true);
    try {
      const data = await staffPost<{ codes: string[] }>("/pilot-codes", { count: Number(count), reason });
      setCodes(data.codes);
    } catch (e) {
      setError(e instanceof StaffApiError ? e.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: "18px", margin: "0 0 12px" }}>Pilots</h1>
      <Section title="Generate pilot codes">
        <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "0 0 8px" }}>
          Single-use codes that grant a 30 day Growth trial at registration. 1 to 50 per action. To extend an existing
          pilot, open the account and use Extend the pilot.
        </p>
        <form onSubmit={generate} style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginBottom: "12px" }}>
          <input style={{ ...inputStyle, width: "80px" }} type="number" min={1} max={50} value={count} onChange={(e) => setCount(e.target.value)} />
          <input
            style={{ ...inputStyle, width: "360px" }}
            placeholder="Reason (min 10 characters)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <button type="submit" disabled={busy} style={buttonStyle}>
            Generate
          </button>
        </form>
        <ErrorLine message={error} />
        {codes.length > 0 && (
          <pre style={{ ...mono, fontSize: "13px", border: "1px solid var(--color-border)", padding: "12px", margin: 0 }}>
            {codes.join("\n")}
          </pre>
        )}
      </Section>
    </div>
  );
}
