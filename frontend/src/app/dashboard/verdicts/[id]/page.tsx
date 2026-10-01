"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentScore {
  agent_name: string;
  score: number;
  triggered: boolean;
}

interface VerdictDetail {
  id: string;
  timestamp: string;
  ip: string;
  method: string | null;
  endpoint: string | null;
  threat_type: string | null;
  severity: string;
  confidence: number;
  agents_triggered: string[] | null;
  explanation: string | null;
  blocked: boolean;
  cost_prevented: number | null;
  created_at: string;
  sample_logs: string[] | null;
  agent_scores: AgentScore[] | null;
  geo_country: string | null;
  geo_asn_number: number | null;
  geo_asn_org: string | null;
  ip_first_seen: string | null;
  ip_last_seen: string | null;
  ip_total_requests: number | null;
  viewer_role: string;
  org_tier: string;
  waf_block_error: string | null;
  cloudflare_block_error: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SEV_COLOR: Record<string, string> = {
  critical: "var(--color-critical)",
  high:     "var(--color-high)",
  medium:   "var(--color-medium)",
  low:      "var(--color-low)",
};

const THREAT_LABELS: Record<string, string> = {
  DOS: "DoS Flood",
  DDOS: "DDoS",
  BRUTE_FORCE: "Brute Force",
  CREDENTIAL_STUFFING: "Credential Stuffing",
  BOT_ACTIVITY: "Bot Activity",
  SCRAPING: "Scraping",
  PORT_SCAN: "Port Scan",
  ENUMERATION: "Enumeration",
  SEQUENCE_ABUSE: "Sequence Abuse",
  WEB_ATTACK: "Web Attack",
  GEO_ANOMALY: "Geo Anomaly",
  UNKNOWN_ABUSE: "Unknown Abuse",
  manual: "Manual Block",
};

function threatLabel(t: string | null): string {
  if (!t) return "Unknown";
  return THREAT_LABELS[t] ?? t;
}

function fmtDateTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--color-text-muted)", marginBottom: "10px" }}>
      {children}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function VerdictDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [v, setV] = useState<VerdictDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [blocking, setBlocking] = useState(false);
  const [blockError, setBlockError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setLoading(true);
    apiFetch(`/verdicts/${id}`)
      .then(async r => {
        if (r.status === 404) {
          setError("Verdict not found.");
          return;
        }
        if (!r.ok) {
          setError("Something went wrong loading this verdict. Try again, or contact support if it keeps happening.");
          return;
        }
        setV(await r.json());
      })
      .catch(() => setError("Could not connect to the server. Try again."))
      .finally(() => setLoading(false));
  }, [id]);

  async function handleBlock() {
    if (!v) return;
    setBlocking(true);
    setBlockError(null);
    try {
      const action = v.blocked ? "unblock" : "block";
      const r = await apiFetch(`/verdicts/${v.id}/${action}`, { method: "POST" });
      if (r.status === 403) {
        const d = await r.json().catch(() => ({}));
        setBlockError(d?.detail ?? "Blocking is not available on your plan.");
        return;
      }
      if (!r.ok) {
        setBlockError("Could not reach the server. Try again.");
        return;
      }
      // The actual AWS/Cloudflare push happens asynchronously in a Celery
      // task, so `blocked` won't flip immediately. Give it a moment, then
      // refetch and surface whatever per-integration error IpMemory recorded
      // if the IP still isn't blocked, instead of the button just going
      // quiet with no explanation either way.
      await new Promise(resolve => setTimeout(resolve, 2500));
      const updated = await apiFetch(`/verdicts/${id}`);
      if (updated.ok) {
        const data: VerdictDetail = await updated.json();
        setV(data);
        if (action === "block" && !data.blocked) {
          setBlockError(
            data.waf_block_error || data.cloudflare_block_error || "Block is still pending. Check back shortly."
          );
        }
      }
    } finally {
      setBlocking(false);
    }
  }

  function copyIp() {
    if (!v) return;
    navigator.clipboard?.writeText(v.ip).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }

  if (loading) {
    return <main style={{ padding: "32px", color: "var(--color-text-muted)", fontSize: "13px" }}>Loading…</main>;
  }
  if (error || !v) {
    return <main style={{ padding: "32px", color: "var(--color-text-muted)", fontSize: "13px" }}>{error ?? "Not found."}</main>;
  }

  // Mirrors api/tiers.py's MANUAL_BLOCK_TIERS (item 55): Basic (starter) can
  // block too, not just Growth/Pro. Unblock has no tier gate at all backend-
  // side, a downgraded org must still be able to remove its own blocks.
  const canManage = v.viewer_role === "owner" || v.viewer_role === "admin";
  const MANUAL_BLOCK_TIERS = ["starter", "growth", "pro", "enterprise"];
  const canBlock = canManage && (v.blocked || MANUAL_BLOCK_TIERS.includes(v.org_tier));
  const hasThreatExplanations = ["growth", "pro", "enterprise"].includes(v.org_tier);

  return (
    <main style={{ padding: "32px", maxWidth: "820px", width: "100%" }}>
      <button
        onClick={() => router.back()}
        style={{ background: "none", border: "none", color: "var(--color-text-muted)", fontSize: "12px", cursor: "pointer", padding: 0, marginBottom: "16px" }}
      >
        ← Back
      </button>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "28px", flexWrap: "wrap", gap: "16px" }}>
        <div>
          <h1
            onClick={copyIp}
            title="Click to copy"
            style={{ fontFamily: "var(--font-mono)", fontSize: "28px", fontWeight: 700, cursor: "pointer", marginBottom: "6px" }}
          >
            {copied ? "Copied!" : v.ip}
          </h1>
          <p style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>
            {v.geo_country ?? "Unknown"}
            {v.geo_asn_org && ` · ${v.geo_asn_org}`}
            {v.geo_asn_number && ` AS${v.geo_asn_number}`}
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{
            display: "inline-block", padding: "4px 10px", fontSize: "12px", fontWeight: 600,
            letterSpacing: "0.06em", textTransform: "uppercase", color: "#fff",
            background: SEV_COLOR[v.severity] ?? "#888",
          }}>
            {v.severity}
          </span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "13px", color: "var(--color-text-muted)" }}>
            {(v.confidence * 100).toFixed(0)}% confidence
          </span>
        </div>
      </div>

      {/* Summary fields */}
      <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)", padding: "20px", marginBottom: "24px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
          <div>
            <SectionLabel>Attack type</SectionLabel>
            <p style={{ fontSize: "14px" }}>{threatLabel(v.threat_type)}</p>
          </div>
          <div>
            <SectionLabel>Detected at</SectionLabel>
            <p style={{ fontSize: "14px", fontFamily: "var(--font-mono)" }}>{fmtDateTime(v.timestamp)}</p>
          </div>
          <div>
            <SectionLabel>First seen / Last seen</SectionLabel>
            <p style={{ fontSize: "14px", fontFamily: "var(--font-mono)" }}>
              {v.ip_first_seen ? fmtDateTime(v.ip_first_seen) : "—"} / {v.ip_last_seen ? fmtDateTime(v.ip_last_seen) : "—"}
            </p>
          </div>
          <div>
            <SectionLabel>Total requests</SectionLabel>
            <p style={{ fontSize: "14px", fontFamily: "var(--font-mono)" }}>{v.ip_total_requests?.toLocaleString() ?? "—"}</p>
          </div>
        </div>
      </div>

      {/* Agent scores */}
      {v.agent_scores && v.agent_scores.length > 0 && (
        <div style={{ marginBottom: "24px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <SectionLabel>Agent scores</SectionLabel>
            <Link href="/docs#the-detection-agents" style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
              How the agents work →
            </Link>
          </div>
          <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
              <thead>
                <tr>
                  {["Agent", "Score", "Triggered"].map(h => (
                    <th key={h} style={{
                      padding: "10px 16px", textAlign: "left", fontSize: "11px",
                      textTransform: "uppercase", letterSpacing: "0.06em",
                      color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", fontWeight: 500,
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {v.agent_scores.map(a => (
                  <tr key={a.agent_name} style={{ borderBottom: "1px solid var(--color-border)", fontWeight: a.triggered ? 700 : 400 }}>
                    <td style={{ padding: "10px 16px" }}>{a.agent_name}</td>
                    <td style={{ padding: "10px 16px", fontFamily: "var(--font-mono)" }}>{a.score.toFixed(2)}</td>
                    <td style={{ padding: "10px 16px", color: a.triggered ? "var(--color-text)" : "var(--color-text-muted)" }}>
                      {a.triggered ? "Yes" : "No"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Raw log sample */}
      {v.sample_logs && v.sample_logs.length > 0 && (
        <div style={{ marginBottom: "24px" }}>
          <SectionLabel>Raw log sample</SectionLabel>
          <pre style={{
            fontFamily: "var(--font-mono)", fontSize: "11px", lineHeight: "1.6",
            border: "1px solid var(--color-border)", background: "var(--color-bg)",
            padding: "16px", overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all",
            margin: 0,
          }}>
            {v.sample_logs.join("\n")}
          </pre>
          <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "6px" }}>
            {v.sample_logs.length} most suspicious request{v.sample_logs.length !== 1 ? "s" : ""} from this batch.
          </p>
        </div>
      )}

      {/* Threat explanations: Growth+ only, per FEATURE_ROWS */}
      <div style={{ marginBottom: "24px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <SectionLabel>AI analysis</SectionLabel>
          <Link href="/docs#threat-explanations" style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
            Learn more →
          </Link>
        </div>
        <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)", padding: "20px" }}>
          {hasThreatExplanations ? (
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>
              {v.explanation || "No explanation available for this verdict."}
            </p>
          ) : (
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)", display: "flex", alignItems: "center", gap: "8px" }}>
              <svg width="14" height="14" viewBox="0 0 14 14" style={{ flexShrink: 0 }}>
                <circle cx="7" cy="7" r="6" fill="none" stroke="var(--color-text)" strokeWidth="1.3" />
                <line x1="3.1" y1="10.9" x2="10.9" y2="3.1" stroke="var(--color-text)" strokeWidth="1.3" />
              </svg>
              Upgrade to Growth to unlock threat explanations.
            </p>
          )}
        </div>
      </div>

      {/* Actions */}
      <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: blockError ? "10px" : 0 }}>
        {canBlock && (
          <button
            onClick={handleBlock}
            disabled={blocking}
            style={{
              padding: "8px 20px", fontSize: "13px",
              border: v.blocked ? "1px solid var(--color-border)" : "1px solid var(--color-text)",
              background: v.blocked ? "transparent" : "var(--color-text)",
              color: v.blocked ? "var(--color-text)" : "var(--color-bg)",
              cursor: blocking ? "default" : "pointer",
              opacity: blocking ? 0.6 : 1,
            }}
          >
            {blocking ? "Working…" : v.blocked ? "Unblock this IP" : "Block this IP"}
          </button>
        )}
        <Link href={`/dashboard/alerts?ip=${v.ip}`} style={{ fontSize: "13px", color: "var(--color-text-muted)", textDecoration: "none" }}>
          View all verdicts for this IP →
        </Link>
      </div>
      {blockError && (
        <p style={{ fontSize: "12px", color: "var(--color-critical)", margin: 0 }}>{blockError}</p>
      )}
    </main>
  );
}
