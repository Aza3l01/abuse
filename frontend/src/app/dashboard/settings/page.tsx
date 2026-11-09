"use client";

import { useEffect, useState } from "react";
import { useRouter }           from "next/navigation";
import Link                    from "next/link";
import { apiFetch }            from "@/lib/api";
import { SITE_URL }            from "@/lib/urls";
import { TeamMembersSection }  from "@/components/dashboard/TeamMembers";
import { ReferralSection }     from "@/components/dashboard/ReferralSection";
import { GuidedOnboardingButton } from "@/components/dashboard/GuidedOnboardingButton";
import { BillingSection }      from "@/components/dashboard/BillingSection";
import { AWS_REGIONS } from "@/lib/awsRegions";
import { LoadingCursor } from "@/components/dashboard/LoadingCursor";
import { WouldHaveBlockedTable } from "@/components/dashboard/WouldHaveBlockedTable";
import { DetectionTuningSection, type DetectionConfig } from "@/components/dashboard/DetectionTuningSection";
// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ClientConfig {
  id: string;
  company_name: string;
  tier: string;
  role: string;
  s3_bucket: string | null;
  s3_prefix: string | null;
  log_format: string | null;
  aws_region: string | null;
  last_processed_key: string | null;
  calibration_status: string | null;
  s3_status: string | null;
  s3_status_message: string | null;
  s3_connected_at: string | null;
  last_scan_completed_at: string | null;
  last_scan_status: string | null;
  last_scan_error: string | null;
  alert_email: string | null;
  alert_severity_threshold: string;
  waf_ip_set_id: string | null;
  cloudflare_zone_id: string | null;
  blocking_tos_accepted_at: string | null;
  auto_block_enabled: boolean;
  auto_block_dry_run: boolean;
  detection_config: DetectionConfig | null;
  home_country: string | null;
  aws_role_arn: string | null;
  aws_external_id: string | null;
  clew_aws_account_id: string;
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

// Item 61: common countries for the home-country select. Not an exhaustive
// ISO 3166-1 list, covers the markets this product actually serves today;
// extend as new customer countries come up.
const HOME_COUNTRIES: [string, string][] = [
  ["IN", "India"],
  ["US", "United States"],
  ["GB", "United Kingdom"],
  ["CA", "Canada"],
  ["AU", "Australia"],
  ["DE", "Germany"],
  ["FR", "France"],
  ["NL", "Netherlands"],
  ["IE", "Ireland"],
  ["SG", "Singapore"],
  ["AE", "United Arab Emirates"],
  ["JP", "Japan"],
  ["BR", "Brazil"],
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

// Mirrors api/tiers.py's MANUAL_BLOCK_TIERS (item 55/69): which tiers get
// the manual block/unblock button and therefore need the Blocking
// Subscription Agreement accepted before checkout.
const MANUAL_BLOCK_TIERS = ["starter", "growth", "pro", "enterprise"];

// The Referrals section is hidden for now. Set to true to show it again.
const SHOW_REFERRALS = false;
// Mirrors api/tiers.py's AUTO_BLOCK_TIERS: Basic (starter) can push a manual
// block, but only Growth and above get the unattended pipeline-triggered
// block, so the WAF/Cloudflare section copy needs to say which one a given
// tier actually gets instead of describing automatic blocking to everyone.
const AUTO_BLOCK_TIERS = ["growth", "pro", "enterprise"];
// Mirrors api/tiers.py's CUSTOM_THRESHOLD_TIERS (Phase 8): custom detection
// thresholds are a Pro and Enterprise feature.
const CUSTOM_THRESHOLD_TIERS = ["pro", "enterprise"];

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
// IAM Policy snippet: phase 2, cross-account sts:AssumeRole
// ---------------------------------------------------------------------------

const preStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "11px",
  background: "transparent",
  margin: 0,
  padding: 0,
  whiteSpace: "pre-wrap",
  wordBreak: "break-all",
  color: "var(--color-text)",
  lineHeight: "1.6",
};

function IamPolicyGuide({
  bucket,
  externalId,
  clewAccountId,
  roleArn,
  setRoleArn,
  onSaveRole,
  savingRole,
  roleTestResult,
}: {
  bucket: string;
  externalId: string | null;
  clewAccountId: string;
  roleArn: string;
  setRoleArn: (v: string) => void;
  onSaveRole: (e: React.FormEvent) => void;
  savingRole: boolean;
  roleTestResult: { status: string; message: string } | null;
}) {
  const [includeBlocking, setIncludeBlocking] = useState(false);
  const [copied, setCopied] = useState(false);
  const bucketName = bucket || "<YOUR-BUCKET-NAME>";
  const accountId = clewAccountId || "<CLEW_AWS_ACCOUNT_ID not yet configured, contact support@clewsec.com>";

  const trustPolicy = JSON.stringify({
    Version: "2012-10-17",
    Statement: [{
      Effect: "Allow",
      Principal: { AWS: `arn:aws:iam::${accountId}:root` },
      Action: "sts:AssumeRole",
      Condition: { StringEquals: { "sts:ExternalId": externalId || "<YOUR-EXTERNAL-ID>" } },
    }],
  }, null, 2);

  const permissionsStatements: Record<string, unknown>[] = [{
    Effect: "Allow",
    Action: ["s3:GetObject", "s3:ListBucket"],
    Resource: [`arn:aws:s3:::${bucketName}`, `arn:aws:s3:::${bucketName}/*`],
  }];
  if (includeBlocking) {
    permissionsStatements.push({
      Effect: "Allow",
      Action: ["wafv2:GetIPSet", "wafv2:UpdateIPSet"],
      Resource: "*",
    });
  }
  const permissionsPolicy = JSON.stringify({ Version: "2012-10-17", Statement: permissionsStatements }, null, 2);

  function copyExternalId() {
    if (!externalId) return;
    navigator.clipboard.writeText(externalId).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div style={{
      border: "1px solid var(--color-border)",
      background: "var(--color-bg)",
      padding: "16px",
    }}>
      <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "16px" }}>
        Clew reads your logs by assuming an IAM role inside your own AWS
        account, not by holding a long-lived access key. Create the role
        below with the two policies shown, then paste its ARN back in.
      </p>

      <FieldRow label="Your External ID">
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <code style={{
            fontFamily: "var(--font-mono)", fontSize: "12px", padding: "6px 10px",
            border: "1px solid var(--color-border)", background: "var(--color-surface)",
            flex: 1, wordBreak: "break-all",
          }}>
            {externalId || "Not yet generated"}
          </code>
          <button
            type="button"
            onClick={copyExternalId}
            disabled={!externalId}
            style={{ padding: "6px 10px", fontSize: "12px", border: "1px solid var(--color-border)", background: "var(--color-bg)", cursor: externalId ? "pointer" : "default" }}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </FieldRow>
      <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginBottom: "16px" }}>
        This is a secret shared only between you and Clew, generated once for
        your organisation. Never share it outside this page.
      </p>

      <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "0 0 6px" }}>
        1. Create an IAM role in your AWS account with this trust policy:
      </p>
      <pre style={preStyle}>{trustPolicy}</pre>

      <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "16px 0 6px" }}>
        2. Attach this permissions policy to the same role:
      </p>
      <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "6px" }}>
        <input type="checkbox" checked={includeBlocking} onChange={e => setIncludeBlocking(e.target.checked)} />
        Also include WAF blocking permissions
      </label>
      <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginBottom: "6px" }}>
        Required for both manual and automatic blocking, not just automatic.
        Completing the setup above with only the S3 statement gives Clew read
        access to your logs but does not enable blocking. If you already
        created a role using the S3-only policy, tick this box, copy the
        updated policy, and update that same role&apos;s existing permissions
        policy, you do not need a second role.
      </p>
      <pre style={preStyle}>{permissionsPolicy}</pre>

      <form onSubmit={onSaveRole} style={{ marginTop: "20px" }}>
        <FieldRow label="Your Role ARN">
          <input
            type="text"
            value={roleArn}
            onChange={e => setRoleArn(e.target.value)}
            placeholder="arn:aws:iam::123456789012:role/ClewAccessRole"
            style={inputStyle}
          />
        </FieldRow>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <button
            type="submit"
            disabled={savingRole}
            style={{
              padding: "8px 20px", fontSize: "13px", border: "1px solid var(--color-text)",
              background: "var(--color-text)", color: "var(--color-bg)",
              cursor: savingRole ? "default" : "pointer", opacity: savingRole ? 0.6 : 1,
            }}
          >
            {savingRole ? "Testing…" : "Save & Test Connection"}
          </button>
          {roleTestResult && (
            <span style={{
              fontSize: "12px",
              color: roleTestResult.status === "connected" ? "var(--color-low)"
                : roleTestResult.status === "saved" ? "var(--color-text-muted)"
                : "var(--color-critical)",
            }}>
              {roleTestResult.message}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const [config,   setConfig]   = useState<ClientConfig | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [saving,   setSaving]   = useState(false);
  const [saved,    setSaved]    = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  // Item 8's RBAC: Settings is owner/admin only, hidden from the sidebar for
  // viewers, but the route itself has no guard, so a viewer who types the
  // URL directly previously got the full (entirely non-functional, every
  // write 403s) form instead of being told they don't have access.
  const [accessDenied, setAccessDenied] = useState(false);

  // Form fields
  const [s3Bucket,     setS3Bucket]     = useState("");
  const [s3Prefix,     setS3Prefix]     = useState("");
  const [logFormat,    setLogFormat]    = useState("");
  const [awsRegion,    setAwsRegion]    = useState("");
  const [alertEmail,   setAlertEmail]   = useState("");
  const [alertSeverityThreshold, setAlertSeverityThreshold] = useState("all");
  const [homeCountry,  setHomeCountry]  = useState("");

  // Item 22: WAF / Cloudflare config (Growth+ only)
  const [wafIpSetId,       setWafIpSetId]       = useState("");
  const [cloudflareZoneId, setCloudflareZoneId] = useState("");
  const [cloudflareToken,  setCloudflareToken]  = useState("");
  const [testingWaf,        setTestingWaf]        = useState(false);
  const [wafTestResult,     setWafTestResult]     = useState<{ status: string; message: string } | null>(null);
  const [testingCloudflare, setTestingCloudflare] = useState(false);
  const [cfTestResult,      setCfTestResult]      = useState<{ status: string; message: string } | null>(null);

  // Phase 2: cross-account AWS IAM role (S3 read + WAF blocking)
  const [awsRoleArn,     setAwsRoleArn]     = useState("");
  const [savingRole,     setSavingRole]     = useState(false);
  const [roleTestResult, setRoleTestResult] = useState<{ status: string; message: string } | null>(null);

  // Item 22: change password (Security section)
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword,     setNewPassword]     = useState("");
  const [pwChanging,      setPwChanging]       = useState(false);
  const [pwMessage,       setPwMessage]        = useState<{ ok: boolean; text: string } | null>(null);

  // Blocking Subscription Agreement. Payments accept it inside the purchase
  // dialog (components/dashboard/PurchaseDialog.tsx). Here it is accepted for
  // the automatic-blocking toggle, and for pilot orgs that never paid.
  const [blockingTosPendingAction, setBlockingTosPendingAction] = useState<
    { kind: "auto_block" } | null
  >(null);
  const [blockingTosBusy, setBlockingTosBusy] = useState(false);
  const [blockingTosError, setBlockingTosError] = useState<string | null>(null);
  // Phase 8: dry run for automatic blocking
  const [savingDryRun, setSavingDryRun] = useState(false);
  const [dryRunError,  setDryRunError]  = useState<string | null>(null);
  // TODO.md priority item 2: auto-block on/off toggle (Growth+ only)
  const [savingAutoBlock, setSavingAutoBlock] = useState(false);
  const [autoBlockError,  setAutoBlockError]  = useState<string | null>(null);


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
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [revoking,        setRevoking]        = useState<string | null>(null);
  const [revokingAll,     setRevokingAll]     = useState(false);

  // Item 40: account deletion
  const router = useRouter();
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting,        setDeleting]        = useState(false);
  const [deleteError,     setDeleteError]     = useState<string | null>(null);

  function loadConfig() {
    return apiFetch(`/clients/me`)
      .then(r => {
        if (r.status === 403) {
          setAccessDenied(true);
          throw new Error("forbidden");
        }
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
        setAlertSeverityThreshold(c.alert_severity_threshold || "all");
        setWafIpSetId(c.waf_ip_set_id ?? "");
        setCloudflareZoneId(c.cloudflare_zone_id ?? "");
        setHomeCountry(c.home_country ?? "");
        setAwsRoleArn(c.aws_role_arn ?? "");
      });
  }

  useEffect(() => {
    // A viewer is refused by /clients/me, so check the role first and skip the 403.
    apiFetch(`/auth/orgs`)
      .then(r => r.ok ? r.json() : [])
      .catch(() => [])
      .then((rows: { role: string; active: boolean }[]) => {
        const active = rows.find(o => o.active) ?? rows[0];
        if (active?.role === "viewer") {
          setAccessDenied(true);
          setLoading(false);
          return;
        }
        return loadConfig()
          .catch(() => setError("Failed to load settings."))
          .finally(() => setLoading(false));
      });

    // mfa_enabled moved to /auth/me (Phase 2 — /clients/me is org config now)
    apiFetch(`/auth/me`)
      .then(r => r.ok ? r.json() : null)
      .then((me: { mfa_enabled?: boolean } | null) => {
        if (me) setMfaEnabled(me.mfa_enabled ?? false);
      })
      .catch(() => {/* handled by the /clients/me fetch above */});

    // Load sessions in parallel
    apiFetch(`/auth/sessions`)
      .then(r => r.ok ? r.json() : [])
      .then((rows: SessionRow[]) => setSessions(rows))
      .catch(() => {/* ignore — sessions are non-critical */})
      .finally(() => setSessionsLoading(false));
  }, []);

  // The page renders a "Loading…" placeholder until `config` (and the rest
  // of the async state above) resolves, so an anchor target like #mfa isn't
  // in the DOM yet at mount time. A hard page load re-runs the browser's own
  // hash-scroll after paint and works fine; client-side navigation (every
  // in-app link) does not re-trigger that, so do it manually once the real
  // content has rendered.
  useEffect(() => {
    if (typeof window === "undefined" || loading) return;
    const hash = window.location.hash.slice(1);
    if (!hash) return;
    const id = requestAnimationFrame(() => {
      document.getElementById(hash)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(id);
  }, [loading]);

  // Records the Blocking Subscription Agreement. `resumeAutoBlock` turns
  // automatic blocking on straight after, for the toggle's own modal.
  async function acceptBlockingTos(resumeAutoBlock: boolean) {
    setBlockingTosBusy(true);
    setBlockingTosError(null);
    try {
      const r = await apiFetch(`/clients/me/accept-blocking-tos`, { method: "POST" });
      if (r.ok) {
        const updated: ClientConfig = await r.json();
        setConfig(updated);
        setBlockingTosPendingAction(null);
        if (resumeAutoBlock) saveAutoBlockEnabled(true);
      } else {
        const d = await r.json().catch(() => ({}));
        setBlockingTosError(typeof d?.detail === "string" ? d.detail : "Could not record acceptance. Please try again.");
      }
    } catch {
      setBlockingTosError("Network error. Please try again.");
    } finally {
      setBlockingTosBusy(false);
    }
  }

  // TODO.md priority item 2: persists auto_block_enabled directly, the
  // backend itself also enforces blocking_tos_accepted_at (api/routes/
  // clients.py), this is the Settings-page gate that surfaces the
  // acceptance modal instead of a plain 400 error.
  async function saveAutoBlockEnabled(next: boolean) {
    setSavingAutoBlock(true);
    setAutoBlockError(null);
    try {
      const r = await apiFetch(`/clients/me`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_block_enabled: next }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setAutoBlockError(d?.detail ?? "Could not update automatic blocking.");
        return;
      }
      setConfig(await r.json());
    } catch {
      setAutoBlockError("Network error. Please try again.");
    } finally {
      setSavingAutoBlock(false);
    }
  }

  function handleAutoBlockToggle(next: boolean) {
    setAutoBlockError(null);
    if (next && !config?.blocking_tos_accepted_at) {
      setBlockingTosPendingAction({ kind: "auto_block" });
      return;
    }
    saveAutoBlockEnabled(next);
  }

  // Phase 8: dry run records what automatic blocking would have blocked
  // without pushing anything to the customer's edge.
  async function saveDryRun(next: boolean) {
    setSavingDryRun(true);
    setDryRunError(null);
    try {
      const r = await apiFetch(`/clients/me`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_block_dry_run: next }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setDryRunError(typeof d?.detail === "string" ? d.detail : "Could not update dry run.");
        return;
      }
      setConfig(await r.json());
    } catch {
      setDryRunError("Network error. Please try again.");
    } finally {
      setSavingDryRun(false);
    }
  }

  async function handleMfaSetup() {
    setMfaSetupLoading(true);
    setMfaSetupError(null);
    try {
      const r = await apiFetch(`/auth/mfa/setup`, {
        method: "POST",
      });
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
      const r = await apiFetch(`/auth/mfa/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: mfaConfirmCode }),
      });
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
      const r = await apiFetch(`/auth/mfa/disable`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: mfaDisablePass }),
      });
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
      await apiFetch(`/auth/sessions/${id}`, {
        method: "DELETE",
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
      await apiFetch(`/auth/sessions`, {
        method: "DELETE",
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
      alert_severity_threshold: alertSeverityThreshold,
      home_country: homeCountry || null,
    };

    try {
      const r = await apiFetch(`/clients/me`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        setError(data?.detail ?? "Save failed.");
        return;
      }
      const updated: ClientConfig = await r.json();
      setConfig(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  // Phase 2: cross-account IAM role ARN, own Save-and-Test button, same
  // pattern as WAF/Cloudflare below. The connection test itself runs
  // server-side (api/routes/clients.py's update_me), triggered by
  // aws_role_arn being present in the PATCH body, so this handler only
  // needs to read the result back off the updated org, not call a
  // separate /settings/test-* endpoint.
  async function handleSaveAwsRole(e: React.FormEvent) {
    e.preventDefault();
    setSavingRole(true);
    setRoleTestResult(null);
    try {
      const r = await apiFetch(`/clients/me`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ aws_role_arn: awsRoleArn || null }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setRoleTestResult({ status: "error", message: d?.detail ?? "Save failed." });
        return;
      }
      const updated: ClientConfig = await r.json();
      setConfig(updated);
      if (!updated.s3_bucket) {
        setRoleTestResult({ status: "saved", message: "Role saved. Set your S3 bucket below to test the connection." });
      } else if (updated.s3_status === "connected") {
        setRoleTestResult({ status: "connected", message: "Connected." });
      } else {
        setRoleTestResult({ status: "error", message: updated.s3_status_message ?? "Could not verify the connection yet." });
      }
    } catch {
      setRoleTestResult({ status: "error", message: "Network error. Please try again." });
    } finally {
      setSavingRole(false);
    }
  }

  // Item 23: WAF / Cloudflare test-and-save (own section, own Save button)
  async function handleSaveWaf(e: React.FormEvent) {
    e.preventDefault();
    setTestingWaf(true);
    setWafTestResult(null);
    try {
      const r = await apiFetch(`/clients/me`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ waf_ip_set_id: wafIpSetId || null }),
      });
      if (r.ok) setConfig(await r.json());
      const tr = await apiFetch(`/settings/test-waf`, { method: "POST" });
      const d = await tr.json().catch(() => ({}));
      setWafTestResult(d.status ? d : { status: "error", message: d.detail ?? "Test failed." });
    } catch {
      setWafTestResult({ status: "error", message: "Network error. Please try again." });
    } finally {
      setTestingWaf(false);
    }
  }

  async function handleSaveCloudflare(e: React.FormEvent) {
    e.preventDefault();
    setTestingCloudflare(true);
    setCfTestResult(null);
    try {
      const body: Record<string, string | null> = { cloudflare_zone_id: cloudflareZoneId || null };
      if (cloudflareToken) body.cloudflare_token = cloudflareToken;
      const r = await apiFetch(`/clients/me`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) setConfig(await r.json());
      const tr = await apiFetch(`/settings/test-cloudflare`, { method: "POST" });
      const d = await tr.json().catch(() => ({}));
      setCfTestResult(d.status ? d : { status: "error", message: d.detail ?? "Test failed." });
    } catch {
      setCfTestResult({ status: "error", message: "Network error. Please try again." });
    } finally {
      setTestingCloudflare(false);
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwChanging(true);
    setPwMessage(null);
    try {
      const r = await apiFetch(`/auth/change-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setPwMessage({ ok: false, text: d?.detail ?? "Failed to change password." });
        return;
      }
      setCurrentPassword("");
      setNewPassword("");
      setPwMessage({ ok: true, text: d?.message ?? "Password changed." });
    } catch {
      setPwMessage({ ok: false, text: "Network error. Please try again." });
    } finally {
      setPwChanging(false);
    }
  }

  async function handleDeleteAccount() {
    setDeleting(true);
    setDeleteError(null);
    try {
      const r = await apiFetch(`/auth/delete-account`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: deleteConfirmText }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setDeleteError(d?.detail ?? "Could not delete account.");
        return;
      }
      router.push("/login");
    } catch {
      setDeleteError("Network error. Please try again.");
    } finally {
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <main style={{ padding: "32px", color: "var(--color-text-muted)", fontSize: "13px" }}>
        Loading<LoadingCursor />
      </main>
    );
  }

  if (accessDenied) {
    return (
      <main style={{ padding: "32px" }}>
        <h1 style={{ fontFamily: "var(--font-brand)", fontSize: "22px", fontWeight: 700, marginBottom: "12px" }}>
          Settings
        </h1>
        <p style={{ fontSize: "13px", color: "var(--color-text-muted)", maxWidth: "480px", lineHeight: 1.6 }}>
          You don&apos;t have access to this page. Settings is only available to
          organisation owners and admins. Ask an owner or admin on your team if
          you need something changed here.
        </p>
      </main>
    );
  }

  return (
    <main style={{ padding: "32px", width: "100%" }}>

      <h1 style={{ fontFamily: "var(--font-brand)", fontSize: "22px", fontWeight: 700, marginBottom: "32px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "16px" }}>
        Settings
        <span style={{ fontSize: "13px", fontWeight: 400 }}>
          <GuidedOnboardingButton label="Reopen guided onboarding" />
        </span>
      </h1>

      {/* ------------------------------------------------------------------ */}
      {/* Plan & Billing                                                      */}
      {/* ------------------------------------------------------------------ */}
      <section id="billing" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Plan & Billing"
          sub="Your plan, open bills, receipts and billing details."
        />

        <BillingSection
          blockingTosAccepted={!!config?.blocking_tos_accepted_at}
          onPlanChanged={() => { loadConfig().catch(() => {}); }}
        />
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Referrals: hidden for now. ReferralSection and its API stay in the  */}
      {/* codebase, flip SHOW_REFERRALS to bring the section back.            */}
      {/* ------------------------------------------------------------------ */}
      {SHOW_REFERRALS && (
      <section id="referrals" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Referrals"
          sub="Invite other organisations and earn a recurring discount for every one that becomes a paying customer."
        />
        <ReferralSection myRole={config?.role ?? null} />
      </section>
      )}

      {/* Blocking Subscription Agreement modal for the automatic-blocking
          toggle, which needs the agreement accepted before it can be switched
          on. Payments accept it inside the purchase dialog instead. */}
      {blockingTosPendingAction && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(13,13,13,0.6)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
        }}>
          <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", padding: "24px", maxWidth: "460px", width: "90%", animation: "modal-panel-in 150ms ease-out" }}>
            <p style={{ fontSize: "14px", fontWeight: 600, marginBottom: "12px" }}>
              Automatic blocking is an active security action
            </p>
            <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "10px", lineHeight: 1.5 }}>
              Once turned on, Clew will add malicious IPs to your AWS WAF and Cloudflare account automatically, with no click required, whenever a high-confidence threat is detected. This is an active security action, not just monitoring.
            </p>
            <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "20px", lineHeight: 1.5 }}>
              By continuing, you accept the{" "}
              <a href={`${SITE_URL}/legal/subscription-agreement`} target="_blank" style={{ color: "var(--color-text)" }}>
                Blocking Subscription Agreement ↗
              </a>.
            </p>
            {blockingTosError && (
              <p style={{ fontSize: "12px", color: "var(--color-critical)", marginBottom: "12px" }}>{blockingTosError}</p>
            )}
            <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
              <button
                onClick={() => { setBlockingTosPendingAction(null); setBlockingTosError(null); }}
                style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={() => acceptBlockingTos(true)}
                disabled={blockingTosBusy}
                style={{
                  padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-text)",
                  background: "var(--color-text)", color: "var(--color-bg)",
                  cursor: blockingTosBusy ? "default" : "pointer", opacity: blockingTosBusy ? 0.6 : 1,
                }}
              >
                {blockingTosBusy ? "Working…" : "I understand, turn on automatic blocking"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* S3 Ingestion                                                        */}
      {/* ------------------------------------------------------------------ */}
      <section id="s3" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="S3 Log Ingestion"
          sub="Clew reads logs from your S3 bucket every 15 minutes. Configure the bucket and log format below."
        />
        <p style={{ fontSize: "12px", marginBottom: "16px" }}>
          <Link href={`${SITE_URL}/docs#connecting-your-log-source`} style={{ color: "var(--color-text-muted)" }}>
            Full setup guide, including API Gateway and ALB logging, in the docs →
          </Link>
        </p>

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
              <option value="">Select region</option>
              {AWS_REGIONS.map(r => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </FieldRow>

          <FieldRow label="Home country">
            <select
              value={homeCountry}
              onChange={e => setHomeCountry(e.target.value)}
              style={selectStyle}
            >
              <option value="">Not set</option>
              {HOME_COUNTRIES.map(([code, name]) => (
                <option key={code} value={code}>{name}</option>
              ))}
            </select>
            <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "6px" }}>
              Where your traffic normally comes from. Helps detection tell foreign
              concentration apart from your own normal traffic.
            </p>
          </FieldRow>

          {/* Item 16: S3 connection status badge */}
          {config?.s3_status && (
            <FieldRow label="Connection">
              <div style={{
                display: "inline-block", padding: "6px 12px", fontSize: "12px",
                border: `1px solid ${config.s3_status === "connected" ? "var(--color-low)" : "var(--color-critical)"}`,
                color: config.s3_status === "connected" ? "var(--color-low)" : "var(--color-critical)",
              }}>
                {config.s3_status === "connected"
                  ? `Connected${config.s3_connected_at ? `, last connected ${new Date(config.s3_connected_at).toLocaleString()}` : ""}`
                  : `Error: ${config.s3_status_message ?? "connection failed"}`}
              </div>
            </FieldRow>
          )}
          {config && !config.s3_status && config.s3_bucket && (
            <FieldRow label="Connection">
              <div style={{ display: "inline-block", padding: "6px 12px", fontSize: "12px", color: "var(--color-text-muted)", border: "1px solid var(--color-border)" }}>
                Not tested, click Save to test
              </div>
            </FieldRow>
          )}

          {/* ---------------------------------------------------------------- */}
          {/* Alerts                                                           */}
          {/* ---------------------------------------------------------------- */}
          <div id="alerts" style={{ borderTop: "1px solid var(--color-border)", margin: "24px 0" }} />
          <SectionTitle
            title="Alerts"
            sub="Receive an email when a high or critical threat is detected."
          />

          {config?.tier === "free" && (
            <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "16px" }}>
              Email alerts require an active paid plan. You can set these up
              now, but no email will send until you upgrade.
            </p>
          )}

          <FieldRow label="Alert email">
            <input
              type="email"
              value={alertEmail}
              onChange={e => setAlertEmail(e.target.value)}
              placeholder="security@yourcompany.com"
              style={inputStyle}
            />
          </FieldRow>

          <FieldRow label="Send alerts for">
            <select
              value={alertSeverityThreshold}
              onChange={e => setAlertSeverityThreshold(e.target.value)}
              style={selectStyle}
            >
              <option value="all">All threats</option>
              <option value="high_critical_only">High + Critical only</option>
            </select>
          </FieldRow>

          <FieldRow label="">
            <a href="/alerts" style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
              Send a test alert on the Alerts page →
            </a>
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
          title="AWS Access"
          sub="Grant Clew read access to your S3 bucket via a cross-account IAM role. No access keys are ever shared."
        />
        <IamPolicyGuide
          bucket={s3Bucket}
          externalId={config?.aws_external_id ?? null}
          clewAccountId={config?.clew_aws_account_id ?? ""}
          roleArn={awsRoleArn}
          setRoleArn={setAwsRoleArn}
          onSaveRole={handleSaveAwsRole}
          savingRole={savingRole}
          roleTestResult={roleTestResult}
        />
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Blocking Subscription Agreement for orgs that never paid (a pilot). */}
      {/* Paying accepts it in the purchase dialog.                           */}
      {/* ------------------------------------------------------------------ */}
      {config && MANUAL_BLOCK_TIERS.includes(config.tier) && !config.blocking_tos_accepted_at && (
      <section id="blocking-agreement" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Blocking Subscription Agreement"
          sub="Blocking adds malicious IPs to your AWS WAF and Cloudflare account. It is an active security action, so the agreement must be accepted before any block is pushed."
        />
        <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "12px", lineHeight: 1.5 }}>
          <a href={`${SITE_URL}/legal/subscription-agreement`} target="_blank" style={{ color: "var(--color-text)" }}>
            Read the Blocking Subscription Agreement ↗
          </a>
        </p>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <button
            type="button"
            onClick={() => acceptBlockingTos(false)}
            disabled={blockingTosBusy}
            style={{
              padding: "8px 20px", fontSize: "13px", border: "1px solid var(--color-text)",
              background: "var(--color-text)", color: "var(--color-bg)",
              cursor: blockingTosBusy ? "default" : "pointer", opacity: blockingTosBusy ? 0.6 : 1,
            }}
          >
            {blockingTosBusy ? "Working…" : "I accept the agreement"}
          </button>
          {blockingTosError && !blockingTosPendingAction && (
            <span style={{ fontSize: "12px", color: "var(--color-critical)" }}>{blockingTosError}</span>
          )}
        </div>
      </section>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* TODO.md priority item 2: automatic blocking on/off toggle          */}
      {/* (Growth and above only, Basic's manual blocking is unaffected)     */}
      {/* ------------------------------------------------------------------ */}
      {config && AUTO_BLOCK_TIERS.includes(config.tier) && (
      <section id="auto-block" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Automatic Blocking"
          sub="Automatically push a block rule to whichever integration below is configured, the moment a high-confidence threat is detected. Off by default, no click required once on."
        />
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <button
            type="button"
            onClick={() => handleAutoBlockToggle(!config.auto_block_enabled)}
            disabled={savingAutoBlock}
            style={{
              padding: "8px 20px",
              fontSize: "13px",
              border: "1px solid var(--color-text)",
              background: config.auto_block_enabled ? "var(--color-text)" : "transparent",
              color: config.auto_block_enabled ? "var(--color-bg)" : "var(--color-text)",
              cursor: savingAutoBlock ? "default" : "pointer",
              opacity: savingAutoBlock ? 0.6 : 1,
              transition: "background 150ms, color 150ms",
            }}
          >
            {savingAutoBlock ? "Saving…" : config.auto_block_enabled ? "On" : "Off"}
          </button>
          {!config.blocking_tos_accepted_at && (
            <span style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
              Requires accepting the Blocking Subscription Agreement first.
            </span>
          )}
          {autoBlockError && (
            <span style={{ fontSize: "12px", color: "var(--color-critical)" }}>{autoBlockError}</span>
          )}
        </div>

        <div style={{ marginTop: "24px" }}>
          <h3 style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "4px" }}>
            Dry run
          </h3>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "12px", lineHeight: 1.5, maxWidth: "640px" }}>
            Record what automatic blocking would have blocked without sending anything to your WAF or Cloudflare.
            It only applies while Automatic Blocking is on. Turn it off to start blocking for real.
          </p>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <button
              type="button"
              onClick={() => saveDryRun(!config.auto_block_dry_run)}
              disabled={savingDryRun}
              style={{
                padding: "8px 20px",
                fontSize: "13px",
                border: "1px solid var(--color-text)",
                background: config.auto_block_dry_run ? "var(--color-text)" : "transparent",
                color: config.auto_block_dry_run ? "var(--color-bg)" : "var(--color-text)",
                cursor: savingDryRun ? "default" : "pointer",
                opacity: savingDryRun ? 0.6 : 1,
                transition: "background 150ms, color 150ms",
              }}
            >
              {savingDryRun ? "Saving…" : config.auto_block_dry_run ? "On" : "Off"}
            </button>
            {config.auto_block_dry_run && !config.auto_block_enabled && (
              <span style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
                Automatic Blocking is off, so nothing is being recorded.
              </span>
            )}
            {dryRunError && (
              <span style={{ fontSize: "12px", color: "var(--color-critical)" }}>{dryRunError}</span>
            )}
          </div>
          {(config.auto_block_dry_run || config.auto_block_enabled) && (
            <WouldHaveBlockedTable refreshKey={config.auto_block_dry_run} />
          )}
        </div>
      </section>
      )}

      {/* Basic (internal tier "starter") can block manually but does not get
          the unattended pipeline-triggered block, so show what it is missing
          and where to get it instead of hiding the section. */}
      {config && config.tier === "starter" && (
      <section id="auto-block" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Automatic Blocking"
          sub="Automatic, unattended blocking is available on Growth and above. On Basic you block manually with one click from a verdict."
        />
        <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)", padding: "16px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "16px", flexWrap: "wrap" }}>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: 0, lineHeight: 1.5, maxWidth: "560px" }}>
            With Growth, Clew pushes a block rule to your WAF or Cloudflare the moment a high-confidence threat is detected, with no click required.
          </p>
          <a
            href="#billing"
            style={{
              padding: "8px 20px",
              fontSize: "13px",
              border: "1px solid var(--color-text)",
              background: "var(--color-text)",
              color: "var(--color-bg)",
              textDecoration: "none",
              whiteSpace: "nowrap",
            }}
          >
            Upgrade to Growth
          </a>
        </div>
      </section>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Phase 8: custom detection thresholds (Pro and Enterprise only)      */}
      {/* ------------------------------------------------------------------ */}
      {config && CUSTOM_THRESHOLD_TIERS.includes(config.tier) && (
      <section id="detection-tuning" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Detection Tuning"
          sub="Set your own confidence thresholds, per-agent minimums and per-endpoint minimums. Blank fields use the defaults. Changes apply from the next scan."
        />
        <DetectionTuningSection config={config.detection_config} onSaved={updated => setConfig(updated as ClientConfig)} />
      </section>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* WAF Configuration (any MANUAL_BLOCK_TIERS org), items 22/23         */}
      {/* ------------------------------------------------------------------ */}
      {config && MANUAL_BLOCK_TIERS.includes(config.tier) && (
      <section id="waf" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="WAF Configuration"
          sub={
            AUTO_BLOCK_TIERS.includes(config.tier)
              ? "Push a block rule to your AWS WAF IP set when a high-confidence threat is detected."
              : "Push a block rule to your AWS WAF IP set with one click from a verdict. Automatic, unattended blocking is available on Growth and above."
          }
        />
        <p style={{ fontSize: "12px", marginBottom: "16px" }}>
          <Link href={`${SITE_URL}/docs#blocking-ips`} style={{ color: "var(--color-text-muted)" }}>
            How manual and automatic blocking work →
          </Link>
        </p>
        <form onSubmit={handleSaveWaf}>
          <FieldRow label="WAF IP set (name::id)">
            <input
              type="text"
              value={wafIpSetId}
              onChange={e => setWafIpSetId(e.target.value)}
              placeholder="name::ip-set-id"
              style={inputStyle}
            />
          </FieldRow>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <button
              type="submit"
              disabled={testingWaf}
              style={{ padding: "8px 20px", fontSize: "13px", border: "1px solid var(--color-text)", background: "var(--color-text)", color: "var(--color-bg)", cursor: testingWaf ? "default" : "pointer", opacity: testingWaf ? 0.6 : 1 }}
            >
              {testingWaf ? "Testing…" : "Save & Test WAF Connection"}
            </button>
            {wafTestResult && (
              <span style={{ fontSize: "12px", color: wafTestResult.status === "connected" ? "var(--color-low)" : "var(--color-critical)" }}>
                {wafTestResult.message}
              </span>
            )}
          </div>
        </form>
      </section>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Cloudflare Configuration (any MANUAL_BLOCK_TIERS org), items 22/23  */}
      {/* ------------------------------------------------------------------ */}
      {config && MANUAL_BLOCK_TIERS.includes(config.tier) && (
      <section id="cloudflare" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Cloudflare Configuration"
          sub={
            AUTO_BLOCK_TIERS.includes(config.tier)
              ? "Push a block rule to your Cloudflare zone when a high-confidence threat is detected."
              : "Push a block rule to your Cloudflare zone with one click from a verdict. Automatic, unattended blocking is available on Growth and above."
          }
        />
        <form onSubmit={handleSaveCloudflare}>
          <FieldRow label="Zone ID">
            <input
              type="text"
              value={cloudflareZoneId}
              onChange={e => setCloudflareZoneId(e.target.value)}
              placeholder="Cloudflare zone ID"
              style={inputStyle}
            />
          </FieldRow>
          <FieldRow label="API token">
            <input
              type="password"
              value={cloudflareToken}
              onChange={e => setCloudflareToken(e.target.value)}
              placeholder={config.cloudflare_zone_id ? "Leave blank to keep the current token" : "Cloudflare API token"}
              style={inputStyle}
            />
          </FieldRow>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <button
              type="submit"
              disabled={testingCloudflare}
              style={{ padding: "8px 20px", fontSize: "13px", border: "1px solid var(--color-text)", background: "var(--color-text)", color: "var(--color-bg)", cursor: testingCloudflare ? "default" : "pointer", opacity: testingCloudflare ? 0.6 : 1 }}
            >
              {testingCloudflare ? "Testing…" : "Save & Test Cloudflare Connection"}
            </button>
            {cfTestResult && (
              <span style={{ fontSize: "12px", color: cfTestResult.status === "connected" ? "var(--color-low)" : "var(--color-critical)" }}>
                {cfTestResult.message}
              </span>
            )}
          </div>
        </form>
      </section>
      )}

      {config && !MANUAL_BLOCK_TIERS.includes(config.tier) && (
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Blocking Integrations"
          sub="Push block rules to your WAF or Cloudflare zone when a high-confidence threat is detected."
        />
        <div style={{ border: "1px solid var(--color-border)", padding: "20px", background: "var(--color-surface)" }}>
          <p style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>
            Available on any paid plan. Upgrade above to configure WAF and Cloudflare blocking.
          </p>
        </div>
      </section>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Webhook Alerts (item 34, POST-MVP): placeholder only, Growth+      */}
      {/* ------------------------------------------------------------------ */}
      {config && (config.tier === "growth" || config.tier === "pro") && (
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Webhook Alerts"
          sub="Send threat notifications to Slack or a custom webhook URL."
        />
        <div style={{ border: "1px solid var(--color-border)", padding: "20px", background: "var(--color-surface)" }}>
          <p style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>
            Coming soon.
          </p>
        </div>
      </section>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* API Keys (item 35, POST-MVP): placeholder only                     */}
      {/* ------------------------------------------------------------------ */}
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="API Keys"
          sub="Create named keys to access the Clew public API."
        />
        <div style={{ border: "1px solid var(--color-border)", padding: "20px", background: "var(--color-surface)" }}>
          <p style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>
            Coming soon.
          </p>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Two-Factor Authentication                                           */}
      {/* ------------------------------------------------------------------ */}
      <section id="mfa" style={{ marginBottom: "40px" }}>
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
                <p style={{ fontSize: "13px", fontWeight: 600, marginBottom: "6px" }}>MFA enabled: save your backup codes</p>
                <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "14px" }}>
                  These 10 single-use codes let you sign in if you lose access to your
                  authenticator app. Save them somewhere safe, they will <strong>not</strong> be shown again.
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
                  I&apos;ve saved them, Done
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
      {/* Change Password (item 22's Security section)                        */}
      {/* ------------------------------------------------------------------ */}
      <section id="security" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Change Password"
          sub="Requires your current password. Other active sessions will be signed out."
        />
        <form onSubmit={handleChangePassword} style={{ border: "1px solid var(--color-border)", padding: "20px", background: "var(--color-bg)" }}>
          <FieldRow label="Current password">
            <input
              type="password"
              autoComplete="current-password"
              required
              value={currentPassword}
              onChange={e => setCurrentPassword(e.target.value)}
              style={inputStyle}
            />
          </FieldRow>
          <FieldRow label="New password">
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              style={inputStyle}
            />
          </FieldRow>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <button
              type="submit"
              disabled={pwChanging}
              style={{ padding: "8px 20px", fontSize: "13px", border: "1px solid var(--color-text)", background: "var(--color-text)", color: "var(--color-bg)", cursor: pwChanging ? "default" : "pointer", opacity: pwChanging ? 0.6 : 1 }}
            >
              {pwChanging ? "Changing…" : "Change Password"}
            </button>
            {pwMessage && (
              <span style={{ fontSize: "12px", color: pwMessage.ok ? "var(--color-low)" : "var(--color-critical)" }}>
                {pwMessage.text}
              </span>
            )}
          </div>
        </form>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Active Sessions                                                      */}
      {/* ------------------------------------------------------------------ */}
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Active Sessions"
          sub="All devices currently signed in to your account."
        />
        <div style={{ border: "1px solid var(--color-border)", background: "var(--color-bg)" }}>
          {sessionsLoading && (
            <p style={{ padding: "20px", fontSize: "12px", color: "var(--color-text-muted)" }}>Loading<LoadingCursor /></p>
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

      {/* ------------------------------------------------------------------ */}
      {/* Team Members (item 9)                                              */}
      {/* ------------------------------------------------------------------ */}
      <section id="team" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Team Members"
          sub="Invite teammates to your organisation. Owners can change roles or remove members."
        />
        <p style={{ fontSize: "12px", marginBottom: "16px" }}>
          <Link href={`${SITE_URL}/docs#team-and-roles`} style={{ color: "var(--color-text-muted)" }}>
            What each role can do →
          </Link>
        </p>
        <TeamMembersSection myRole={config?.role ?? null} onOwnershipTransferred={loadConfig} />
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Account deletion (item 40)                                          */}
      {/* ------------------------------------------------------------------ */}
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Danger Zone"
          sub="Permanently delete your account and all associated data."
        />
        <div style={{ border: "1px solid var(--color-critical)", padding: "20px", background: "var(--color-bg)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "16px", flexWrap: "wrap" }}>
            <div>
              <p style={{ fontSize: "13px", fontWeight: 600, marginBottom: "4px" }}>Delete account and all data</p>
              <p style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
                This cannot be undone. All verdicts, IP intelligence, and settings are permanently deleted within 30 days.
              </p>
            </div>
            <button
              type="button"
              onClick={() => { setDeleteModalOpen(true); setDeleteConfirmText(""); setDeleteError(null); }}
              style={{
                padding: "8px 16px", fontSize: "12px", flexShrink: 0,
                border: "1px solid var(--color-critical)",
                background: "transparent", color: "var(--color-critical)", cursor: "pointer",
              }}
            >
              Delete my account
            </button>
          </div>
        </div>
      </section>

      {/* Item 40: account deletion confirmation modal */}
      {deleteModalOpen && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(13,13,13,0.6)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
        }}>
          <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", padding: "24px", maxWidth: "460px", width: "90%", animation: "modal-panel-in 150ms ease-out" }}>
            <p style={{ fontSize: "14px", fontWeight: 600, marginBottom: "12px", color: "var(--color-critical)" }}>
              Delete your account?
            </p>
            <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "10px", lineHeight: 1.5 }}>
              This cannot be undone. Your data will be permanently deleted within 30 days.
            </p>
            {config?.role === "owner" && (
              <p style={{ fontSize: "12px", color: "var(--color-critical)", marginBottom: "10px", lineHeight: 1.5 }}>
                You own {config?.company_name ?? "this organisation"}. Deleting your account deletes the
                entire organisation, its data, and every other member&apos;s access to it. To keep the
                organisation instead, use &quot;Make owner&quot; in Team Members above to transfer
                ownership to an admin first. Any active subscription will be cancelled.
              </p>
            )}
            <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "16px", lineHeight: 1.5 }}>
              Type <strong style={{ color: "var(--color-text)" }}>DELETE</strong> to confirm.
            </p>
            <input
              type="text"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              style={{ ...inputStyle, marginBottom: "16px" }}
              autoFocus
            />
            {deleteError && (
              <p style={{ fontSize: "12px", color: "var(--color-critical)", marginBottom: "12px" }}>{deleteError}</p>
            )}
            <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
              <button
                onClick={() => setDeleteModalOpen(false)}
                style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteAccount}
                disabled={deleting || deleteConfirmText !== "DELETE"}
                style={{
                  padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-critical)",
                  background: "var(--color-critical)", color: "var(--color-bg)",
                  cursor: (deleting || deleteConfirmText !== "DELETE") ? "default" : "pointer",
                  opacity: (deleting || deleteConfirmText !== "DELETE") ? 0.6 : 1,
                }}
              >
                {deleting ? "Deleting…" : "Delete my account"}
              </button>
            </div>
          </div>
        </div>
      )}

    </main>
  );
}
