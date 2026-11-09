"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";

// Mirrors api/detection_config.py (the backend validates again).
const AGENTS: [string, string][] = [
  ["VolumeAgent", "Volume"],
  ["TemporalAgent", "Timing"],
  ["AuthAgent", "Authentication"],
  ["PayloadAgent", "Payload"],
  ["SequenceAgent", "Sequence"],
  ["GeoIPAgent", "Geography"],
];
const MAX_ENDPOINTS = 20;

export interface DetectionConfig {
  attack_threshold?: number;
  block_confidence_threshold?: number;
  agent_min_confidence?: Record<string, number>;
  endpoint_thresholds?: { pattern: string; min_confidence: number }[];
}

interface EndpointRow { pattern: string; min: string }

const inputStyle: React.CSSProperties = {
  padding: "7px 10px", fontSize: "13px", border: "1px solid var(--color-border)",
  background: "var(--color-surface)", color: "var(--color-text)", fontFamily: "var(--font-geist-mono, monospace)",
};

const buttonStyle: React.CSSProperties = {
  padding: "8px 20px", fontSize: "13px", border: "1px solid var(--color-text)",
  background: "var(--color-text)", color: "var(--color-bg)",
};

const ghostButtonStyle: React.CSSProperties = {
  padding: "8px 20px", fontSize: "13px", border: "1px solid var(--color-border)",
  background: "transparent", color: "var(--color-text)",
};

function errorText(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0 && typeof detail[0]?.msg === "string") {
    return detail[0].msg.replace(/^Value error,\s*/, "");
  }
  return fallback;
}

function Field({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: "16px", marginBottom: "16px" }}>
      <label style={{ width: "160px", flexShrink: 0, fontSize: "12px", color: "var(--color-text-muted)", paddingTop: "8px" }}>
        {label}
      </label>
      <div style={{ flex: 1 }}>
        {children}
        <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginTop: "4px", lineHeight: 1.5 }}>{hint}</p>
      </div>
    </div>
  );
}

// Phase 8, Pro and Enterprise: the customer's own detection thresholds.
// Blank fields use the engine defaults.
export function DetectionTuningSection({
  config,
  onSaved,
}: {
  config: DetectionConfig | null;
  onSaved: (updated: unknown) => void;
}) {
  const [attack, setAttack] = useState(config?.attack_threshold?.toString() ?? "");
  const [block, setBlock] = useState(config?.block_confidence_threshold?.toString() ?? "");
  const [agents, setAgents] = useState<Record<string, string>>(
    Object.fromEntries(AGENTS.map(([key]) => [key, config?.agent_min_confidence?.[key]?.toString() ?? ""])),
  );
  const [endpoints, setEndpoints] = useState<EndpointRow[]>(
    (config?.endpoint_thresholds ?? []).map(e => ({ pattern: e.pattern, min: e.min_confidence.toString() })),
  );
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  function buildConfig(): DetectionConfig {
    const out: DetectionConfig = {};
    if (attack.trim() !== "") out.attack_threshold = Number(attack);
    if (block.trim() !== "") out.block_confidence_threshold = Number(block);
    const agentMins: Record<string, number> = {};
    for (const [key] of AGENTS) {
      if (agents[key].trim() !== "") agentMins[key] = Number(agents[key]);
    }
    if (Object.keys(agentMins).length > 0) out.agent_min_confidence = agentMins;
    const rows = endpoints
      .filter(e => e.pattern.trim() !== "" || e.min.trim() !== "")
      .map(e => ({ pattern: e.pattern.trim(), min_confidence: Number(e.min) }));
    if (rows.length > 0) out.endpoint_thresholds = rows;
    return out;
  }

  async function save(body: DetectionConfig, successText: string) {
    setSaving(true);
    setMessage(null);
    try {
      const r = await apiFetch(`/clients/me`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ detection_config: body }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setMessage({ ok: false, text: errorText(d?.detail, "Could not save detection settings.") });
        return;
      }
      onSaved(await r.json());
      setMessage({ ok: true, text: successText });
    } catch {
      setMessage({ ok: false, text: "Network error. Please try again." });
    } finally {
      setSaving(false);
    }
  }

  function handleReset() {
    setAttack("");
    setBlock("");
    setAgents(Object.fromEntries(AGENTS.map(([key]) => [key, ""])));
    setEndpoints([]);
    save({}, "Reset to the defaults.");
  }

  return (
    <form onSubmit={e => { e.preventDefault(); save(buildConfig(), "Saved. Applies from the next scan."); }}>
      <Field label="Attack threshold" hint="Confidence needed to record a detection. Default 0.60. Range 0.40 to 0.90. Lower finds more, raise it to cut noise.">
        <input type="number" step="0.01" min="0.4" max="0.9" value={attack} onChange={e => setAttack(e.target.value)} placeholder="0.60" style={{ ...inputStyle, width: "120px" }} />
      </Field>
      <Field label="Block threshold" hint="Confidence needed before automatic blocking acts. Default 0.75. Range 0.50 to 0.95. Manual blocks are not affected.">
        <input type="number" step="0.01" min="0.5" max="0.95" value={block} onChange={e => setBlock(e.target.value)} placeholder="0.75" style={{ ...inputStyle, width: "120px" }} />
      </Field>

      <div style={{ marginBottom: "16px" }}>
        <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "8px", lineHeight: 1.5 }}>
          Agent minimums: ignore a finding from an agent unless its confidence reaches the minimum (0.50 to 0.95). Leave blank for no minimum.
        </p>
        <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)", maxWidth: "420px" }}>
          {AGENTS.map(([key, label]) => (
            <div key={key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 16px", borderBottom: "1px solid var(--color-border)" }}>
              <span style={{ fontSize: "13px" }}>{label}</span>
              <input
                type="number" step="0.01" min="0.5" max="0.95" aria-label={`${label} minimum`}
                value={agents[key]} onChange={e => setAgents(prev => ({ ...prev, [key]: e.target.value }))}
                style={{ ...inputStyle, width: "100px" }}
              />
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginBottom: "16px" }}>
        <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "8px", lineHeight: 1.5 }}>
          Endpoint minimums: a detection on a matching endpoint is dropped if its confidence is below the minimum (0.50 to 0.99).
          A pattern starts with / and may end with * (for example /admin/*). Up to {MAX_ENDPOINTS}.
        </p>
        {endpoints.map((row, i) => (
          <div key={i} style={{ display: "flex", gap: "8px", marginBottom: "8px", maxWidth: "520px" }}>
            <input
              type="text" aria-label="Endpoint pattern" placeholder="/api/login" value={row.pattern}
              onChange={e => setEndpoints(prev => prev.map((p, j) => (j === i ? { ...p, pattern: e.target.value } : p)))}
              style={{ ...inputStyle, flex: 1 }}
            />
            <input
              type="number" step="0.01" min="0.5" max="0.99" aria-label="Endpoint minimum" placeholder="0.90" value={row.min}
              onChange={e => setEndpoints(prev => prev.map((p, j) => (j === i ? { ...p, min: e.target.value } : p)))}
              style={{ ...inputStyle, width: "100px" }}
            />
            <button type="button" onClick={() => setEndpoints(prev => prev.filter((_, j) => j !== i))} style={{ ...ghostButtonStyle, padding: "7px 12px", cursor: "pointer" }}>
              Remove
            </button>
          </div>
        ))}
        {endpoints.length < MAX_ENDPOINTS && (
          <button type="button" onClick={() => setEndpoints(prev => [...prev, { pattern: "", min: "" }])} style={{ ...ghostButtonStyle, cursor: "pointer" }}>
            Add endpoint
          </button>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
        <button type="submit" disabled={saving} style={{ ...buttonStyle, cursor: saving ? "default" : "pointer", opacity: saving ? 0.6 : 1 }}>
          {saving ? "Saving…" : "Save detection settings"}
        </button>
        <button type="button" onClick={handleReset} disabled={saving} style={{ ...ghostButtonStyle, cursor: saving ? "default" : "pointer", opacity: saving ? 0.6 : 1 }}>
          Reset to defaults
        </button>
        {message && (
          <span style={{ fontSize: "12px", color: message.ok ? "var(--color-low)" : "var(--color-critical)" }}>{message.text}</span>
        )}
      </div>
    </form>
  );
}
