"use client";

// Shared pieces of the internal ops panel. Plain tables, square corners, 1px
// borders, Geist Mono for timestamps and ids (frontend/DESIGN_SYSTEM.md).
import { useState, type CSSProperties, type ReactNode } from "react";
import { StaffApiError, formatCell, staffPost, type Cell, type Kv, type Row } from "@/lib/staffApi";

export const mono: CSSProperties = { fontFamily: "var(--font-geist-mono), 'Courier New', monospace" };

export const inputStyle: CSSProperties = {
  background: "var(--color-bg)",
  color: "var(--color-text)",
  border: "1px solid var(--color-border)",
  borderRadius: 0,
  padding: "6px 8px",
  fontSize: "13px",
};

export const buttonStyle: CSSProperties = {
  background: "var(--color-text)",
  color: "var(--color-bg)",
  border: "1px solid var(--color-text)",
  borderRadius: 0,
  padding: "6px 12px",
  fontSize: "13px",
  cursor: "pointer",
};

export const secondaryButtonStyle: CSSProperties = {
  background: "transparent",
  color: "var(--color-text)",
  border: "1px solid var(--color-border)",
  borderRadius: 0,
  padding: "6px 12px",
  fontSize: "13px",
  cursor: "pointer",
};

const thStyle: CSSProperties = {
  padding: "8px 12px",
  textAlign: "left",
  fontSize: "11px",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  color: "var(--color-text-muted)",
  borderBottom: "1px solid var(--color-border)",
  fontWeight: 500,
  whiteSpace: "nowrap",
};

const tdStyle: CSSProperties = {
  padding: "8px 12px",
  borderBottom: "1px solid var(--color-border)",
  verticalAlign: "top",
  wordBreak: "break-word",
};

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ borderTop: "1px solid var(--color-border)", padding: "16px 0" }}>
      <h2 style={{ fontSize: "13px", textTransform: "uppercase", letterSpacing: "0.06em", margin: "0 0 12px" }}>
        {title}
      </h2>
      {children}
    </section>
  );
}

export function ErrorLine({ message }: { message: string }) {
  if (!message) return null;
  return (
    <p role="alert" style={{ color: "var(--color-critical)", fontSize: "13px", margin: "8px 0" }}>
      {message}
    </p>
  );
}

export function KvTable({ data }: { data: Kv }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
      <tbody>
        {Object.entries(data).map(([key, value]) => (
          <tr key={key}>
            <td style={{ ...tdStyle, width: "260px", color: "var(--color-text-muted)" }}>{key}</td>
            <td style={{ ...tdStyle, ...mono }}>{formatCell(value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export interface Column {
  key: string;
  label: string;
  render?: (row: Row) => ReactNode;
}

export function DataTable({ columns, rows, empty }: { columns: Column[]; rows: Row[]; empty?: string }) {
  if (rows.length === 0) {
    return <p style={{ fontSize: "13px", color: "var(--color-text-muted)", margin: 0 }}>{empty ?? "No rows."}</p>;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={thStyle}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((c) => (
                <td key={c.key} style={{ ...tdStyle, ...mono }}>
                  {c.render ? c.render(row) : formatCell(row[c.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface FieldDef {
  name: string;
  label: string;
  kind: "text" | "number" | "select";
  options?: { value: string; label: string }[];
  initial?: string;
}

/** One staff action: fields, a confirm prompt, a POST to /internal<path>. The
 * reason field is always last and required by the server (10 characters). */
export function ActionForm({
  title,
  help,
  path,
  fields,
  onDone,
}: {
  title: string;
  help?: string;
  /** A fixed path, or one built from the form values (an id picked in a select). */
  path: string | ((values: Record<string, string>) => string);
  fields: FieldDef[];
  onDone?: () => void;
}) {
  const all: FieldDef[] = [...fields, { name: "reason", label: "Reason (audit log, min 10 characters)", kind: "text" }];
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(all.map((f) => [f.name, f.initial ?? f.options?.[0]?.value ?? ""])),
  );
  const [error, setError] = useState("");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setResult("");
    if (!window.confirm(`${title}. This is written to the audit log. Continue?`)) return;
    const body: Record<string, Cell> = {};
    for (const f of all) body[f.name] = f.kind === "number" ? Number(values[f.name]) : values[f.name];
    setBusy(true);
    try {
      await staffPost(typeof path === "function" ? path(values) : path, body);
      setResult("Done.");
      onDone?.();
    } catch (e) {
      setError(e instanceof StaffApiError ? e.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} style={{ border: "1px solid var(--color-border)", padding: "12px", marginBottom: "12px" }}>
      <div style={{ fontSize: "13px", fontWeight: 600 }}>{title}</div>
      {help && <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "4px 0 8px" }}>{help}</p>}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", alignItems: "flex-end" }}>
        {all.map((f) => (
          <label key={f.name} style={{ display: "flex", flexDirection: "column", fontSize: "11px", gap: "4px" }}>
            {f.label}
            {f.kind === "select" ? (
              <select
                style={inputStyle}
                value={values[f.name]}
                onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
              >
                {(f.options ?? []).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                style={{ ...inputStyle, width: f.name === "reason" ? "320px" : f.kind === "number" ? "80px" : "200px" }}
                type={f.kind === "number" ? "number" : "text"}
                value={values[f.name]}
                onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
              />
            )}
          </label>
        ))}
        <button type="submit" disabled={busy} style={buttonStyle}>
          {busy ? "Working" : "Run"}
        </button>
      </div>
      <ErrorLine message={error} />
      {result && <p style={{ fontSize: "13px", margin: "8px 0 0" }}>{result}</p>}
    </form>
  );
}
