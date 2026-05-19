"use client";

import { useEffect, useState } from "react";
import { useRouter }           from "next/navigation";
import { API_URL }             from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ClientConfig {
  id: string;
  email: string;
  company_name: string;
  tier: string;
  mfa_enabled: boolean;
  s3_bucket: string | null;
  s3_prefix: string | null;
  log_format: string | null;
  aws_region: string | null;
  last_processed_key: string | null;
  alert_email: string | null;
  waf_ip_set_id: string | null;
  cloudflare_zone_id: string | null;
}

interface SessionRow {
  id: string;
  user_agent: string | null;
  ip: string | null;
  issued_at: string;
  expires_at: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AWS_REGIONS = [
  "us-east-1", "us-east-2", "us-west-1", "us-west-2",
  "eu-west-1", "eu-west-2", "eu-central-1",
  "ap-south-1", "ap-southeast-1", "ap-southeast-2", "ap-northeast-1",
];

// ---------------------------------------------------------------------------
// Section header helper
// ---------------------------------------------------------------------------

function SectionTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <div style={{ marginBottom: "20px" }}>
      <h2 style={{ fontSize: "13px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "4px" }}>
        {title}
      </h2>
      {sub && <p style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>{sub}</p>}
    </div>
  );
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: "16px", marginBottom: "16px" }}>
      <label style={{
        width: "160px",
        flexShrink: 0,
        fontSize: "12px",
        color: "var(--color-text-muted)",
        paddingTop: "8px",
      }}>
        {label}
      </label>
      <div style={{ flex: 1 }}>{children}</div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 10px",
  fontSize: "13px",
  border: "1px solid var(--color-border)",
  background: "var(--color-surface)",
  color: "var(--color-text)",
  boxSizing: "border-box",
};

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: "pointer",
};

// ---------------------------------------------------------------------------
// IAM Policy snippet
// ---------------------------------------------------------------------------

function IamPolicyGuide({ bucket }: { bucket: string }) {
  const bucketName = bucket || "<YOUR-BUCKET-NAME>";
  const policy = JSON.stringify({
    Version: "2012-10-17",
    Statement: [{
      Effect: "Allow",
      Action: ["s3:GetObject", "s3:ListBucket"],
      Resource: [
        `arn:aws:s3:::${bucketName}`,
        `arn:aws:s3:::${bucketName}/*`,
      ],
    }],
  }, null, 2);

  return (
    <div style={{
      border: "1px solid var(--color-border)",
      background: "var(--color-bg)",
      padding: "16px",
    }}>
      <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "12px" }}>
        Create an IAM user with the policy below and provide its Access Key ID and
        Secret Access Key in your <code style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}>AWS_ACCESS_KEY_ID</code> / <code style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}>AWS_SECRET_ACCESS_KEY</code> environment variables on your Celery worker host.
      </p>
      <pre style={{
        fontFamily: "var(--font-mono)",
        fontSize: "11px",
        background: "transparent",
        margin: 0,
        padding: 0,
        whiteSpace: "pre-wrap",
        wordBreak: "break-all",
        color: "var(--color-text)",
        lineHeight: "1.6",
      }}>
        {policy}
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const router = useRouter();

  const [config,   setConfig]   = useState<ClientConfig | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [saving,   setSaving]   = useState(false);
  const [saved,    setSaved]    = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  // Form fields
  const [s3Bucket,     setS3Bucket]     = useState("");
  const [s3Prefix,     setS3Prefix]     = useState("");
  const [logFormat,    setLogFormat]    = useState("");
  const [awsRegion,    setAwsRegion]    = useState("");
  const [alertEmail,   setAlertEmail]   = useState("");

  // Billing
  const [upgrading,    setUpgrading]    = useState<string | null>(null);
  const [billingError, setBillingError] = useState<string | null>(null);
  const [showUpgraded, setShowUpgraded] = useState(false);
  const [currency,     setCurrency]     = useState<"INR" | "USD">("INR");

  // MFA
  const [mfaEnabled,      setMfaEnabled]      = useState(false);
  const [mfaSetupData,    setMfaSetupData]    = useState<{ secret: string; uri: string } | null>(null);
  const [mfaConfirmCode,  setMfaConfirmCode]  = useState("");
  const [mfaSetupLoading, setMfaSetupLoading] = useState(false);
  const [mfaSetupError,   setMfaSetupError]   = useState<string | null>(null);
  const [backupCodes,     setBackupCodes]     = useState<string[] | null>(null);
  const [mfaDisablePass,  setMfaDisablePass]  = useState("");
  const [mfaDisableShow,  setMfaDisableShow]  = useState(false);
  const [mfaDisableLoading, setMfaDisableLoading] = useState(false);
  const [mfaDisableError, setMfaDisableError] = useState<string | null>(null);

  // Sessions
  const [sessions,        setSessions]        = useState<SessionRow[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [revoking,        setRevoking]        = useState<string | null>(null);
  const [revokingAll,     setRevokingAll]     = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/clients/me`, { credentials: "include" })
      .then(r => {
        if (r.status === 401) { router.push("/login"); return null; }
        if (!r.ok) throw new Error("API error");
        return r.json();
      })
      .then((c: ClientConfig | null) => {
        if (!c) return;
        setConfig(c);
        setS3Bucket(c.s3_bucket ?? "");
        setS3Prefix(c.s3_prefix ?? "");
        setLogFormat(c.log_format ?? "");
        setAwsRegion(c.aws_region ?? "");
        setAlertEmail(c.alert_email ?? "");
        setMfaEnabled(c.mfa_enabled ?? false);
      })
      .catch(() => setError("Failed to load settings."))
      .finally(() => setLoading(false));

    // Load sessions in parallel
    setSessionsLoading(true);
    fetch(`${API_URL}/auth/sessions`, { credentials: "include" })
      .then(r => r.ok ? r.json() : [])
      .then((rows: SessionRow[]) => setSessions(rows))
      .catch(() => {/* ignore — sessions are non-critical */})
      .finally(() => setSessionsLoading(false));
  }, [router]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("upgraded") === "1") {
      setShowUpgraded(true);
      window.history.replaceState({}, "", window.location.pathname);
    }
    const tz   = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const lang = navigator.language || "";
    const isIndia = tz.includes("Kolkata") || tz.includes("Calcutta") || lang === "hi" || lang.endsWith("-IN");
    setCurrency(isIndia ? "INR" : "USD");
  }, []);

  async function handleUpgrade(tier: string) {
    setUpgrading(tier);
    setBillingError(null);
    try {
      const r = await fetch(`${API_URL}/billing/checkout`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier, currency }),
      });
      if (r.status === 401) { router.push("/login"); return; }
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setBillingError(d?.detail ?? "Could not start checkout. Please try again.");
        return;
      }
      const { url } = await r.json();
      window.location.href = url;
    } catch {
      setBillingError("Network error. Please try again.");
    } finally {
      setUpgrading(null);
    }
  }

  async function handleManage() {
    setUpgrading("portal");
    setBillingError(null);
    try {
      const r = await fetch(`${API_URL}/billing/portal`, {
        method: "POST",
        credentials: "include",
      });
      if (r.status === 401) { router.push("/login"); return; }
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setBillingError(d?.detail ?? "Could not open billing portal.");
        return;
      }
      const { url } = await r.json();
      window.location.href = url;
    } catch {
      setBillingError("Network error. Please try again.");
    } finally {
      setUpgrading(null);
    }
  }

  async function handleMfaSetup() {
    setMfaSetupLoading(true);
    setMfaSetupError(null);
    try {
      const r = await fetch(`${API_URL}/auth/mfa/setup`, {
        method: "POST",
        credentials: "include",
      });
      if (r.status === 401) { router.push("/login"); return; }
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setMfaSetupError(d?.detail ?? "Setup failed.");
        return;
      }
      const d = await r.json();
      setMfaSetupData(d);
      setMfaConfirmCode("");
    } catch {
      setMfaSetupError("Network error. Please try again.");
    } finally {
      setMfaSetupLoading(false);
    }
  }

  async function handleMfaVerify(e: React.FormEvent) {
    e.preventDefault();
    setMfaSetupLoading(true);
    setMfaSetupError(null);
    try {
      const r = await fetch(`${API_URL}/auth/mfa/verify`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: mfaConfirmCode }),
      });
      if (r.status === 401) { router.push("/login"); return; }
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setMfaSetupError(d?.detail ?? "Verification failed.");
        return;
      }
      const d = await r.json();
      setMfaEnabled(true);
      setMfaSetupData(null);
      setMfaConfirmCode("");
      setBackupCodes(d.backup_codes ?? null);
    } catch {
      setMfaSetupError("Network error. Please try again.");
    } finally {
      setMfaSetupLoading(false);
    }
  }

  async function handleMfaDisable(e: React.FormEvent) {
    e.preventDefault();
    setMfaDisableLoading(true);
    setMfaDisableError(null);
    try {
      const r = await fetch(`${API_URL}/auth/mfa/disable`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: mfaDisablePass }),
      });
      if (r.status === 401 && !r.headers.get("content-type")?.includes("json")) {
        router.push("/login"); return;
      }
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setMfaDisableError(d?.detail ?? "Failed to disable MFA.");
        return;
      }
      setMfaEnabled(false);
      setMfaDisableShow(false);
      setMfaDisablePass("");
    } catch {
      setMfaDisableError("Network error. Please try again.");
    } finally {
      setMfaDisableLoading(false);
    }
  }

  async function handleRevokeSession(id: string) {
    setRevoking(id);
    try {
      await fetch(`${API_URL}/auth/sessions/${id}`, {
        method: "DELETE",
        credentials: "include",
      });
      setSessions(prev => prev.filter(s => s.id !== id));
    } catch {
      // ignore
    } finally {
      setRevoking(null);
    }
  }

  async function handleRevokeAll() {
    setRevokingAll(true);
    try {
      await fetch(`${API_URL}/auth/sessions`, {
        method: "DELETE",
        credentials: "include",
      });
      setSessions([]);
    } catch {
      // ignore
    } finally {
      setRevokingAll(false);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    setError(null);

    const body: Record<string, string | null> = {
      s3_bucket:   s3Bucket   || null,
      s3_prefix:   s3Prefix   || null,
      log_format:  logFormat  || null,
      aws_region:  awsRegion  || null,
      alert_email: alertEmail || null,
    };

    try {
      const r = await fetch(`${API_URL}/clients/me`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.status === 401) { router.push("/login"); return; }
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        setError(data?.detail ?? "Save failed.");
        return;
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <main style={{ padding: "32px", color: "var(--color-text-muted)", fontSize: "13px" }}>
        Loading…
      </main>
    );
  }

  return (
    <main style={{ padding: "32px", maxWidth: "680px", width: "100%" }}>

      <h1 style={{ fontFamily: "var(--font-brand)", fontSize: "22px", fontWeight: 700, marginBottom: "32px" }}>
        Settings
      </h1>

      {/* ------------------------------------------------------------------ */}
      {/* Plan & Billing                                                      */}
      {/* ------------------------------------------------------------------ */}
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Plan & Billing"
          sub="Manage your subscription and payment method."
        />

        {showUpgraded && (
          <div style={{
            padding: "10px 14px",
            border: "1px solid var(--color-low)",
            marginBottom: "16px",
            fontSize: "12px",
            color: "var(--color-low)",
          }}>
            Plan upgraded successfully. Your new plan is now active.
          </div>
        )}

        {billingError && (
          <div style={{
            padding: "10px 14px",
            border: "1px solid var(--color-critical)",
            marginBottom: "16px",
            fontSize: "12px",
            color: "var(--color-critical)",
          }}>
            {billingError}
          </div>
        )}

        <div style={{
          border: "1px solid var(--color-border)",
          padding: "20px",
          background: "var(--color-bg)",
        }}>
          <div style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: config?.tier !== "free" ? "0" : "14px",
          }}>
            <div>
              <p style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "4px" }}>
                Current plan
              </p>
              <p style={{ fontSize: "18px", fontFamily: "var(--font-brand)", fontWeight: 700, textTransform: "capitalize" }}>
                {config?.tier ?? "—"}
              </p>
            </div>
            {config && config.tier !== "free" && (
              <button
                onClick={handleManage}
                disabled={!!upgrading}
                style={{
                  padding: "7px 16px",
                  fontSize: "12px",
                  border: "1px solid var(--color-border)",
                  background: "transparent",
                  color: "var(--color-text)",
                  cursor: upgrading ? "default" : "pointer",
                  opacity: upgrading ? 0.6 : 1,
                }}
              >
                {upgrading === "portal" ? "Redirecting…" : "Manage billing"}
              </button>
            )}
          </div>

          {config && config.tier === "free" && (
            <>
              <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "16px" }}>
                Upgrade to unlock full threat history, email alerts, and auto-blocking.
              </p>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                {([
                  { tier: "starter", labelINR: "₹6,999/mo", labelUSD: "$99/mo",   note: "10M calls/mo" },
                  { tier: "growth",  labelINR: "₹14,999/mo", labelUSD: "$249/mo", note: "50M · blocking", highlight: true },
                  { tier: "pro",     labelINR: "₹29,999/mo", labelUSD: "$449/mo", note: "200M calls/mo" },
                ] as { tier: string; labelINR: string; labelUSD: string; note: string; highlight?: boolean }[]).map(p => (
                  <button
                    key={p.tier}
                    onClick={() => handleUpgrade(p.tier)}
                    disabled={!!upgrading}
                    style={{
                      padding: "10px 14px",
                      fontSize: "12px",
                      border: p.highlight ? "none" : "1px solid var(--color-border)",
                      background: p.highlight ? "var(--color-text)" : "transparent",
                      color: p.highlight ? "var(--color-bg)" : "var(--color-text)",
                      cursor: upgrading ? "default" : "pointer",
                      opacity: upgrading ? 0.6 : 1,
                      textAlign: "left",
                    }}
                  >
                    <span style={{ fontWeight: 600, textTransform: "capitalize", display: "block" }}>
                      {upgrading === p.tier ? "Redirecting…" : p.tier}
                    </span>
                    <span style={{ opacity: 0.7, fontSize: "11px" }}>
                      {currency === "INR" ? p.labelINR : p.labelUSD} · {p.note}
                    </span>
                  </button>
                ))}
              </div>
              <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "12px" }}>
                Payments by Stripe.{" "}
                Viewing prices in {currency}.{" "}
                <button
                  onClick={() => setCurrency(c => c === "INR" ? "USD" : "INR")}
                  style={{ background: "none", border: "none", color: "var(--color-text-muted)", cursor: "pointer", textDecoration: "underline", fontSize: "11px", padding: 0 }}
                >
                  Switch to {currency === "INR" ? "USD" : "INR"}
                </button>
              </p>
            </>
          )}
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* S3 Ingestion                                                        */}
      {/* ------------------------------------------------------------------ */}
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="S3 Log Ingestion"
          sub="Clew reads logs from your S3 bucket every 15 minutes. Configure the bucket and log format below."
        />

        <form onSubmit={handleSave}>

          <FieldRow label="S3 bucket">
            <input
              type="text"
              value={s3Bucket}
              onChange={e => setS3Bucket(e.target.value)}
              placeholder="my-api-access-logs"
              style={inputStyle}
            />
          </FieldRow>

          <FieldRow label="S3 prefix">
            <input
              type="text"
              value={s3Prefix}
              onChange={e => setS3Prefix(e.target.value)}
              placeholder="logs/ (optional)"
              style={inputStyle}
            />
          </FieldRow>

          <FieldRow label="Log format">
            <select
              value={logFormat}
              onChange={e => setLogFormat(e.target.value)}
              style={selectStyle}
            >
              <option value="">— Select format —</option>
              <option value="apigw">API Gateway (apigw)</option>
              <option value="alb">Application Load Balancer (alb)</option>
            </select>
          </FieldRow>

          <FieldRow label="AWS region">
            <select
              value={awsRegion}
              onChange={e => setAwsRegion(e.target.value)}
              style={selectStyle}
            >
              <option value="">— Select region —</option>
              {AWS_REGIONS.map(r => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </FieldRow>

          {/* ---------------------------------------------------------------- */}
          {/* Alerts                                                           */}
          {/* ---------------------------------------------------------------- */}
          <div style={{ borderTop: "1px solid var(--color-border)", margin: "24px 0" }} />
          <SectionTitle
            title="Alerts"
            sub="Receive an email when a high or critical threat is detected."
          />

          <FieldRow label="Alert email">
            <input
              type="email"
              value={alertEmail}
              onChange={e => setAlertEmail(e.target.value)}
              placeholder="security@yourcompany.com"
              style={inputStyle}
            />
          </FieldRow>

          {/* Save button + feedback */}
          <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "8px" }}>
            <button
              type="submit"
              disabled={saving}
              style={{
                padding: "8px 20px",
                fontSize: "13px",
                border: "1px solid var(--color-text)",
                background: "var(--color-text)",
                color: "var(--color-bg)",
                cursor: saving ? "default" : "pointer",
                opacity: saving ? 0.6 : 1,
              }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
            {saved && (
              <span style={{ fontSize: "12px", color: "var(--color-low)" }}>
                Saved
              </span>
            )}
            {error && (
              <span style={{ fontSize: "12px", color: "var(--color-critical)" }}>
                {error}
              </span>
            )}
          </div>
        </form>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* IAM Policy Guide                                                    */}
      {/* ------------------------------------------------------------------ */}
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="IAM Policy"
          sub="Attach this policy to the AWS IAM user whose credentials your Celery worker uses."
        />
        <IamPolicyGuide bucket={s3Bucket} />
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Blocking (stubbed — Phase 7)                                        */}
      {/* ------------------------------------------------------------------ */}
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Blocking Integrations"
          sub="Automatically push block rules to your WAF or Cloudflare zone when a high-confidence threat is detected."
        />
        <div style={{
          border: "1px solid var(--color-border)",
          padding: "20px",
          background: "var(--color-surface)",
        }}>
          <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "8px" }}>
            Available on Growth and Pro plans.
          </p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
            AWS WAF IP set ID, Cloudflare zone ID and API token configuration
            will be available in the next release.
          </p>
          {config && (
            <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "12px", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Current plan: {config.tier}
            </p>
          )}
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Two-Factor Authentication                                           */}
      {/* ------------------------------------------------------------------ */}
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Two-Factor Authentication"
          sub="Add an extra layer of security to your account with a TOTP authenticator app."
        />
        <div style={{ border: "1px solid var(--color-border)", padding: "20px", background: "var(--color-bg)" }}>

          {mfaEnabled && !mfaDisableShow && !backupCodes && (
            <>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div>
                  <p style={{ fontSize: "13px", fontWeight: 600, marginBottom: "4px" }}>Enabled</p>
                  <p style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
                    Your account is protected with a TOTP authenticator.
                  </p>
                </div>
                <button
                  onClick={() => { setMfaDisableShow(true); setMfaDisableError(null); setMfaDisablePass(""); }}
                  style={{
                    padding: "7px 16px", fontSize: "12px",
                    border: "1px solid var(--color-critical)",
                    background: "transparent", color: "var(--color-critical)", cursor: "pointer",
                  }}
                >
                  Disable MFA
                </button>
              </div>
            </>
          )}

          {mfaEnabled && backupCodes && (
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <div>
                <p style={{ fontSize: "13px", fontWeight: 600, marginBottom: "6px" }}>MFA enabled — save your backup codes</p>
                <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "14px" }}>
                  These 10 single-use codes let you sign in if you lose access to your
                  authenticator app. Save them somewhere safe — they will <strong>not</strong> be shown again.
                </p>
                <div style={{
                  display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px",
                  background: "var(--color-surface)", border: "1px solid var(--color-border)",
                  padding: "14px", fontFamily: "var(--font-mono)", fontSize: "13px",
                  letterSpacing: "0.06em",
                }}>
                  {backupCodes.map(c => (
                    <span key={c}>{c}</span>
                  ))}
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  onClick={() => {
                    const text = backupCodes.join("\n");
                    navigator.clipboard.writeText(text).catch(() => {});
                  }}
                  style={{
                    padding: "7px 16px", fontSize: "12px",
                    border: "1px solid var(--color-border)",
                    background: "transparent", color: "var(--color-text)", cursor: "pointer",
                  }}
                >
                  Copy all
                </button>
                <button
                  onClick={() => setBackupCodes(null)}
                  style={{
                    padding: "7px 20px", fontSize: "12px",
                    border: "1px solid var(--color-text)",
                    background: "var(--color-text)", color: "var(--color-bg)", cursor: "pointer",
                  }}
                >
                  I&apos;ve saved them — Done
                </button>
              </div>
            </div>
          )}

          {mfaEnabled && mfaDisableShow && (
            <form onSubmit={handleMfaDisable} style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
              <p style={{ fontSize: "13px", color: "var(--color-text-muted)", margin: 0 }}>
                Enter your account password to confirm.
              </p>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={mfaDisablePass}
                onChange={e => setMfaDisablePass(e.target.value)}
                placeholder="Current password"
                style={{ padding: "7px 10px", fontSize: "13px", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)", width: "260px", boxSizing: "border-box" }}
              />
              {mfaDisableError && (
                <p style={{ fontSize: "12px", color: "var(--color-critical)", margin: 0 }}>{mfaDisableError}</p>
              )}
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  type="submit"
                  disabled={mfaDisableLoading}
                  style={{
                    padding: "7px 16px", fontSize: "12px",
                    border: "none", background: "var(--color-critical)",
                    color: "#fff", cursor: mfaDisableLoading ? "default" : "pointer",
                    opacity: mfaDisableLoading ? 0.6 : 1,
                  }}
                >
                  {mfaDisableLoading ? "Disabling…" : "Confirm disable"}
                </button>
                <button
                  type="button"
                  onClick={() => { setMfaDisableShow(false); setMfaDisablePass(""); setMfaDisableError(null); }}
                  style={{
                    padding: "7px 16px", fontSize: "12px",
                    border: "1px solid var(--color-border)",
                    background: "transparent", color: "var(--color-text)", cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {!mfaEnabled && !mfaSetupData && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <p style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
                Not enabled. Use any TOTP app such as Google Authenticator or Authy.
              </p>
              <button
                onClick={handleMfaSetup}
                disabled={mfaSetupLoading}
                style={{
                  padding: "7px 16px", fontSize: "12px",
                  border: "1px solid var(--color-text)",
                  background: "var(--color-text)", color: "var(--color-bg)",
                  cursor: mfaSetupLoading ? "default" : "pointer",
                  opacity: mfaSetupLoading ? 0.6 : 1,
                  flexShrink: 0,
                }}
              >
                {mfaSetupLoading ? "Loading…" : "Enable MFA"}
              </button>
            </div>
          )}

          {!mfaEnabled && mfaSetupData && (
            <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
              <div>
                <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "12px" }}>
                  Scan this QR code with your authenticator app, or enter the secret key manually.
                </p>
                {/* QR code via free public API — no npm package needed */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(mfaSetupData.uri)}`}
                  alt="TOTP QR code"
                  width={180}
                  height={180}
                  style={{ display: "block", marginBottom: "12px", border: "1px solid var(--color-border)" }}
                />
                <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginBottom: "4px" }}>
                  Manual key:
                </p>
                <code style={{
                  fontFamily: "var(--font-mono)", fontSize: "13px",
                  letterSpacing: "0.12em", wordBreak: "break-all",
                  color: "var(--color-text)",
                }}>
                  {mfaSetupData.secret}
                </code>
              </div>
              <form onSubmit={handleMfaVerify} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: 0 }}>
                  Enter the 6-digit code from your app to activate MFA.
                </p>
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  required
                  value={mfaConfirmCode}
                  onChange={e => setMfaConfirmCode(e.target.value.replace(/\D/g, ""))}
                  placeholder="000000"
                  style={{
                    padding: "7px 10px", fontSize: "16px", letterSpacing: "0.3em",
                    textAlign: "center", border: "1px solid var(--color-border)",
                    background: "var(--color-surface)", color: "var(--color-text)",
                    width: "140px", boxSizing: "border-box",
                  }}
                />
                {mfaSetupError && (
                  <p style={{ fontSize: "12px", color: "var(--color-critical)", margin: 0 }}>{mfaSetupError}</p>
                )}
                <div style={{ display: "flex", gap: "8px" }}>
                  <button
                    type="submit"
                    disabled={mfaSetupLoading}
                    style={{
                      padding: "7px 20px", fontSize: "12px",
                      border: "1px solid var(--color-text)",
                      background: "var(--color-text)", color: "var(--color-bg)",
                      cursor: mfaSetupLoading ? "default" : "pointer",
                      opacity: mfaSetupLoading ? 0.6 : 1,
                    }}
                  >
                    {mfaSetupLoading ? "Activating…" : "Activate MFA"}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setMfaSetupData(null); setMfaSetupError(null); }}
                    style={{
                      padding: "7px 16px", fontSize: "12px",
                      border: "1px solid var(--color-border)",
                      background: "transparent", color: "var(--color-text)", cursor: "pointer",
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Active Sessions                                                      */}
      {/* ------------------------------------------------------------------ */}
      <section>
        <SectionTitle
          title="Active Sessions"
          sub="All devices currently signed in to your account."
        />
        <div style={{ border: "1px solid var(--color-border)", background: "var(--color-bg)" }}>
          {sessionsLoading && (
            <p style={{ padding: "20px", fontSize: "12px", color: "var(--color-text-muted)" }}>Loading…</p>
          )}
          {!sessionsLoading && sessions.length === 0 && (
            <p style={{ padding: "20px", fontSize: "12px", color: "var(--color-text-muted)" }}>No active sessions found.</p>
          )}
          {!sessionsLoading && sessions.length > 0 && (
            <>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
                    <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 500, color: "var(--color-text-muted)" }}>Device / Browser</th>
                    <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 500, color: "var(--color-text-muted)" }}>IP</th>
                    <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 500, color: "var(--color-text-muted)" }}>Signed in</th>
                    <th style={{ padding: "10px 16px" }} />
                  </tr>
                </thead>
                <tbody>
                  {sessions.map(s => (
                    <tr key={s.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                      <td style={{ padding: "10px 16px", color: "var(--color-text)", maxWidth: "240px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {s.user_agent ?? "Unknown"}
                      </td>
                      <td style={{ padding: "10px 16px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", fontSize: "11px" }}>
                        {s.ip ?? "—"}
                      </td>
                      <td style={{ padding: "10px 16px", color: "var(--color-text-muted)" }}>
                        {new Date(s.issued_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                      </td>
                      <td style={{ padding: "10px 16px", textAlign: "right" }}>
                        <button
                          onClick={() => handleRevokeSession(s.id)}
                          disabled={revoking === s.id}
                          style={{
                            padding: "4px 10px", fontSize: "11px",
                            border: "1px solid var(--color-border)",
                            background: "transparent", color: "var(--color-text)",
                            cursor: revoking === s.id ? "default" : "pointer",
                            opacity: revoking === s.id ? 0.5 : 1,
                          }}
                        >
                          {revoking === s.id ? "…" : "Revoke"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ padding: "12px 16px", borderTop: "1px solid var(--color-border)" }}>
                <button
                  onClick={handleRevokeAll}
                  disabled={revokingAll}
                  style={{
                    padding: "6px 14px", fontSize: "12px",
                    border: "1px solid var(--color-border)",
                    background: "transparent", color: "var(--color-text)",
                    cursor: revokingAll ? "default" : "pointer",
                    opacity: revokingAll ? 0.5 : 1,
                  }}
                >
                  {revokingAll ? "Signing out…" : "Sign out all devices"}
                </button>
              </div>
            </>
          )}
        </div>
      </section>

    </main>
  );
}
