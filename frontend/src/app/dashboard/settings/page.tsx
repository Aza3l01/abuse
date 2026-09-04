"use client";

import { useEffect, useState } from "react";
import { useRouter }           from "next/navigation";
import { apiFetch }            from "@/lib/api";
import { TeamMembersSection }  from "@/components/dashboard/TeamMembers";
import { loadRazorpayCheckout } from "@/lib/razorpay";
import { PRICING_TIERS, FEATURE_ROWS } from "@/lib/pricing";

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
}

interface BillingStatus {
  tier: string;
  billing_provider: string | null;
  payment_method_display: string | null;
  next_billing_date: string | null;
  razorpay_subscription_id: string | null;
}

interface RefundEligibility {
  eligible: boolean;
  reason: "pre_charge" | "remorse_window" | "not_eligible";
  window_expires_at: string | null;
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
  const [alertSeverityThreshold, setAlertSeverityThreshold] = useState("all");

  // Item 22: WAF / Cloudflare config (Growth+ only)
  const [wafIpSetId,       setWafIpSetId]       = useState("");
  const [cloudflareZoneId, setCloudflareZoneId] = useState("");
  const [cloudflareToken,  setCloudflareToken]  = useState("");
  const [testingWaf,        setTestingWaf]        = useState(false);
  const [wafTestResult,     setWafTestResult]     = useState<{ status: string; message: string } | null>(null);
  const [testingCloudflare, setTestingCloudflare] = useState(false);
  const [cfTestResult,      setCfTestResult]      = useState<{ status: string; message: string } | null>(null);

  // Item 22: change password (Security section)
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword,     setNewPassword]     = useState("");
  const [pwChanging,      setPwChanging]       = useState(false);
  const [pwMessage,       setPwMessage]        = useState<{ ok: boolean; text: string } | null>(null);

  // Billing
  const [upgrading,    setUpgrading]    = useState<string | null>(null);
  const [billingError, setBillingError] = useState<string | null>(null);
  const [showUpgraded, setShowUpgraded] = useState(false);
  const [currency,     setCurrency]     = useState<"INR" | "USD">("INR");
  const [period,       setPeriod]       = useState<"monthly" | "annual">("monthly");
  const [gstin,        setGstin]        = useState("");
  const [billingStatus, setBillingStatus] = useState<BillingStatus | null>(null);
  // Item 28: Growth blocking TOS modal, holds the tier the user clicked
  // while the modal is open, so accepting can resume the upgrade.
  const [blockingTosPendingTier, setBlockingTosPendingTier] = useState<string | null>(null);
  const [blockingTosBusy, setBlockingTosBusy] = useState(false);
  // Item 29b: cancel/refund modal
  const [cancelModalOpen, setCancelModalOpen] = useState(false);
  const [refundEligibility, setRefundEligibility] = useState<RefundEligibility | null>(null);
  const [cancelling, setCancelling] = useState(false);


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

  // Item 40: account deletion
  const router = useRouter();
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting,        setDeleting]        = useState(false);
  const [deleteError,     setDeleteError]     = useState<string | null>(null);

  function loadConfig() {
    return apiFetch(`/clients/me`)
      .then(r => {
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
      });
  }

  useEffect(() => {
    loadConfig()
      .catch(() => setError("Failed to load settings."))
      .finally(() => setLoading(false));

    apiFetch(`/billing/status`)
      .then(r => r.ok ? r.json() : null)
      .then((b: BillingStatus | null) => { if (b) setBillingStatus(b); })
      .catch(() => {/* admin/viewer: billing is owner-only, 403 is expected */});

    // mfa_enabled moved to /auth/me (Phase 2 — /clients/me is org config now)
    apiFetch(`/auth/me`)
      .then(r => r.ok ? r.json() : null)
      .then((me: { mfa_enabled?: boolean } | null) => {
        if (me) setMfaEnabled(me.mfa_enabled ?? false);
      })
      .catch(() => {/* handled by the /clients/me fetch above */});

    // Load sessions in parallel
    setSessionsLoading(true);
    apiFetch(`/auth/sessions`)
      .then(r => r.ok ? r.json() : [])
      .then((rows: SessionRow[]) => setSessions(rows))
      .catch(() => {/* ignore — sessions are non-critical */})
      .finally(() => setSessionsLoading(false));
  }, []);

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

  async function handleManage() {
    setUpgrading("portal");
    setBillingError(null);
    try {
      const r = await apiFetch(`/billing/portal`, {
        method: "POST",
      });
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

  // Item 29 currency routing: India → Razorpay checkout below. Everywhere
  // else, Stripe production keys aren't live yet (item 29 MVP scope), so
  // non-India customers are invoiced manually until Stripe ships.
  function handlePlanClick(tier: string) {
    setBillingError(null);
    if (currency !== "INR") {
      setBillingError("USD billing isn't self-serve yet, we'll set up your invoice manually. Contact billing@clewsec.com.");
      return;
    }
    // Item 28: Growth is an active-blocking plan, the TOS modal must be
    // accepted before the payment flow opens, and only once ever.
    if (tier === "growth" && !config?.blocking_tos_accepted_at) {
      setBlockingTosPendingTier(tier);
      return;
    }
    startRazorpayCheckout(tier);
  }

  async function acceptBlockingTosAndContinue() {
    const tier = blockingTosPendingTier;
    if (!tier) return;
    setBlockingTosBusy(true);
    try {
      const r = await apiFetch(`/clients/me/accept-blocking-tos`, { method: "POST" });
      if (r.ok) {
        const updated: ClientConfig = await r.json();
        setConfig(updated);
        setBlockingTosPendingTier(null);
        startRazorpayCheckout(tier);
      } else {
        setBillingError("Could not record acceptance. Please try again.");
      }
    } catch {
      setBillingError("Network error. Please try again.");
    } finally {
      setBlockingTosBusy(false);
    }
  }

  async function startRazorpayCheckout(tier: string) {
    setUpgrading(tier);
    setBillingError(null);
    try {
      await loadRazorpayCheckout();
      const r = await apiFetch(`/billing/razorpay/create-subscription`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier, period, gstin: gstin || null }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setBillingError(d?.detail ?? "Could not start Razorpay checkout. Please try again.");
        setUpgrading(null);
        return;
      }
      const { subscription_id, key_id } = await r.json();
      const rzp = new window.Razorpay({
        key: key_id,
        subscription_id,
        name: "Clew",
        description: `${tier.charAt(0).toUpperCase()}${tier.slice(1)} plan`,
        theme: { color: "#0D0D0D" },
        config: { display: { sequence: ["block.upi", "block.card", "block.netbanking", "block.wallet"] } },
        handler: async (response: {
          razorpay_payment_id: string;
          razorpay_subscription_id: string;
          razorpay_signature: string;
        }) => {
          try {
            const vr = await apiFetch(`/billing/razorpay/verify-payment`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ tier, ...response }),
            });
            if (vr.ok) {
              const status: BillingStatus = await vr.json();
              setBillingStatus(status);
              setConfig(c => c ? { ...c, tier: status.tier } : c);
              setShowUpgraded(true);
            } else {
              const d = await vr.json().catch(() => ({}));
              setBillingError(d?.detail ?? "Payment verification failed. Contact support if you were charged.");
            }
          } finally {
            setUpgrading(null);
          }
        },
        modal: { ondismiss: () => setUpgrading(null) },
      });
      rzp.open();
    } catch {
      setBillingError("Network error. Please try again.");
      setUpgrading(null);
    }
  }

  async function openCancelModal() {
    setCancelModalOpen(true);
    setRefundEligibility(null);
    try {
      const r = await apiFetch(`/billing/refund-eligibility`, { method: "POST" });
      if (r.ok) setRefundEligibility(await r.json());
    } catch {
      /* modal shows a generic message if this fails */
    }
  }

  async function handleCancelConfirm() {
    setCancelling(true);
    try {
      const r = await apiFetch(`/billing/cancel`, { method: "POST" });
      if (r.ok) {
        setCancelModalOpen(false);
        const status: BillingStatus | null = await apiFetch(`/billing/status`).then(res => res.ok ? res.json() : null).catch(() => null);
        if (status) {
          setBillingStatus(status);
          setConfig(c => c ? { ...c, tier: status.tier } : c);
        }
      } else {
        const d = await r.json().catch(() => ({}));
        setBillingError(d?.detail ?? "Could not cancel subscription.");
      }
    } catch {
      setBillingError("Network error. Please try again.");
    } finally {
      setCancelling(false);
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
        Loading…
      </main>
    );
  }

  return (
    <main style={{ padding: "32px", width: "100%" }}>

      <h1 style={{ fontFamily: "var(--font-brand)", fontSize: "22px", fontWeight: 700, marginBottom: "32px" }}>
        Settings
      </h1>

      {/* ------------------------------------------------------------------ */}
      {/* Plan & Billing                                                      */}
      {/* ------------------------------------------------------------------ */}
      <section id="billing" style={{ marginBottom: "40px" }}>
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
            marginBottom: "14px",
          }}>
            <div>
              <p style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "4px" }}>
                Current plan
              </p>
              <p style={{ fontSize: "18px", fontFamily: "var(--font-brand)", fontWeight: 700, textTransform: "capitalize" }}>
                {config?.tier ?? "—"}
              </p>
              {billingStatus?.payment_method_display && (
                <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginTop: "4px" }}>
                  {billingStatus.payment_method_display}
                  {billingStatus.next_billing_date && ` · next billing ${new Date(billingStatus.next_billing_date).toLocaleDateString()}`}
                </p>
              )}
            </div>
            {billingStatus?.billing_provider === "stripe" && (
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
            {billingStatus?.billing_provider === "razorpay" && (
              <button
                onClick={openCancelModal}
                style={{
                  padding: "7px 16px",
                  fontSize: "12px",
                  border: "1px solid var(--color-border)",
                  background: "transparent",
                  color: "var(--color-critical)",
                  cursor: "pointer",
                }}
              >
                Cancel subscription
              </button>
            )}
          </div>

          {billingStatus?.billing_provider !== "stripe" && (
            <>
              <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "16px" }}>
                {billingStatus?.billing_provider === "razorpay"
                  ? "Upgrades start immediately; downgrades take effect at the end of the current billing cycle."
                  : "Add a payment method to unlock full threat history, email alerts, and auto-blocking."}
              </p>

              {currency === "INR" && (
                <div style={{ marginBottom: "20px" }}>
                  <p style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "8px" }}>
                    Billing period (choose before selecting a plan)
                  </p>
                  <div style={{ display: "flex", alignItems: "center", gap: "16px", flexWrap: "wrap" }}>
                    <div style={{ display: "flex", border: "1px solid var(--color-border)" }}>
                      {(["monthly", "annual"] as const).map(p => (
                        <button
                          key={p}
                          onClick={() => setPeriod(p)}
                          style={{
                            padding: "6px 12px",
                            fontSize: "11px",
                            border: "none",
                            background: period === p ? "var(--color-text)" : "transparent",
                            color: period === p ? "var(--color-bg)" : "var(--color-text)",
                            cursor: "pointer",
                            textTransform: "capitalize",
                          }}
                        >
                          {p}{p === "annual" ? " (2 months free)" : ""}
                        </button>
                      ))}
                    </div>
                    <input
                      type="text"
                      placeholder="GSTIN (optional)"
                      value={gstin}
                      onChange={e => setGstin(e.target.value)}
                      style={{ ...inputStyle, width: "180px", padding: "6px 10px", fontSize: "11px" }}
                    />
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-0">
                {PRICING_TIERS
                  .filter(p => p.tier !== config?.tier || billingStatus?.billing_provider !== "razorpay")
                  .map((p, i) => (
                  <div
                    key={p.tier}
                    style={{
                      padding: "24px 20px",
                      borderTop: "1px solid var(--color-border)",
                      borderBottom: "1px solid var(--color-border)",
                      borderRight: "1px solid var(--color-border)",
                      borderLeft: i === 0 ? "1px solid var(--color-border)" : "none",
                      background: p.highlight ? "var(--color-surface)" : "var(--color-bg)",
                      display: "flex",
                      flexDirection: "column",
                    }}
                  >
                    {p.highlight ? (
                      <p style={{ fontFamily: "var(--font-mono)", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--color-text-muted)", marginBottom: "12px" }}>
                        Most popular
                      </p>
                    ) : (
                      <div style={{ height: "17px" }} />
                    )}
                    <p style={{ fontFamily: "var(--font-brand)", fontWeight: 700, fontSize: "18px", marginBottom: "6px" }}>
                      {p.name}
                    </p>
                    <p style={{ fontFamily: "var(--font-brand)", fontWeight: 700, fontSize: "22px", marginBottom: "4px" }}>
                      {p.contactOnly
                        ? "Custom pricing"
                        : (currency === "INR" ? (period === "monthly" ? p.monthlyINR : p.annualINR) : (period === "monthly" ? p.monthlyUSD : p.annualUSD))}
                    </p>
                    <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "20px" }}>
                      {p.volume}
                    </p>
                    <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: "8px", flex: 1, marginBottom: "20px" }}>
                      {FEATURE_ROWS.map((row) => {
                        const value = row.values[i];
                        const included = value !== false;
                        return (
                          <li
                            key={row.label}
                            style={{
                              fontSize: "12px",
                              color: included ? "var(--color-text-muted)" : "var(--color-border)",
                              display: "flex",
                              alignItems: "flex-start",
                              gap: "8px",
                            }}
                          >
                            <span style={{ color: included ? "var(--color-text)" : "var(--color-border)", flexShrink: 0 }}>
                              {included ? "+" : "×"}
                            </span>
                            {row.label}
                            {typeof value === "string" ? ` (${value})` : ""}
                          </li>
                        );
                      })}
                    </ul>
                    {p.contactOnly ? (
                      <a
                        href="mailto:jeff@clewsec.com"
                        style={{
                          padding: "10px 0",
                          fontSize: "13px",
                          fontWeight: 500,
                          textAlign: "center",
                          border: "1px solid var(--color-border)",
                          background: "transparent",
                          color: "var(--color-text)",
                          textDecoration: "none",
                          display: "block",
                        }}
                      >
                        Contact us
                      </a>
                    ) : (
                    <button
                      onClick={() => handlePlanClick(p.tier)}
                      disabled={!!upgrading}
                      style={{
                        padding: "10px 0",
                        fontSize: "13px",
                        fontWeight: 500,
                        width: "100%",
                        border: p.highlight ? "none" : "1px solid var(--color-border)",
                        background: p.highlight ? "var(--color-text)" : "transparent",
                        color: p.highlight ? "var(--color-bg)" : "var(--color-text)",
                        cursor: upgrading ? "default" : "pointer",
                        opacity: upgrading ? 0.6 : 1,
                      }}
                    >
                      {upgrading === p.tier ? "Working…" : "Select"}
                    </button>
                    )}
                  </div>
                ))}
              </div>

              <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "16px" }}>
                {currency === "INR" ? "Payments by Razorpay. UPI, cards, netbanking, and wallets accepted." : "USD billing is invoiced manually for now, Stripe self-serve checkout is coming soon."}{" "}
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

      {/* Item 28: Growth blocking TOS modal */}
      {blockingTosPendingTier && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(13,13,13,0.6)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
        }}>
          <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", padding: "24px", maxWidth: "460px", width: "90%" }}>
            <p style={{ fontSize: "14px", fontWeight: 600, marginBottom: "12px" }}>
              Growth subscription includes active IP blocking
            </p>
            <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "10px", lineHeight: 1.5 }}>
              Clew will automatically add malicious IPs to your AWS WAF and Cloudflare account.
              This is an active security action, not just monitoring.
            </p>
            <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "20px", lineHeight: 1.5 }}>
              By continuing, you accept the{" "}
              <a href="/legal/subscription-agreement" target="_blank" style={{ color: "var(--color-text)" }}>
                Growth Subscription Agreement ↗
              </a>.
            </p>
            <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
              <button
                onClick={() => setBlockingTosPendingTier(null)}
                style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={acceptBlockingTosAndContinue}
                disabled={blockingTosBusy}
                style={{
                  padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-text)",
                  background: "var(--color-text)", color: "var(--color-bg)",
                  cursor: blockingTosBusy ? "default" : "pointer", opacity: blockingTosBusy ? 0.6 : 1,
                }}
              >
                {blockingTosBusy ? "Working…" : "I understand, continue to payment"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Item 29b: cancel/refund modal */}
      {cancelModalOpen && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(13,13,13,0.6)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
        }}>
          <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", padding: "24px", maxWidth: "460px", width: "90%" }}>
            <p style={{ fontSize: "14px", fontWeight: 600, marginBottom: "12px" }}>
              Cancel your subscription?
            </p>
            {refundEligibility === null ? (
              <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "20px" }}>Checking refund eligibility…</p>
            ) : (
              <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "20px", lineHeight: 1.5 }}>
                {refundEligibility.reason === "pre_charge" &&
                  "You haven't been charged yet, cancelling now means no charge will ever occur."}
                {refundEligibility.reason === "remorse_window" &&
                  `You're within 72 hours of your first payment, cancelling now issues a full refund (window closes ${refundEligibility.window_expires_at ? new Date(refundEligibility.window_expires_at).toLocaleString() : "soon"}).`}
                {refundEligibility.reason === "not_eligible" &&
                  "No refund applies at this point. Your plan stays active until the end of the current billing cycle, then cancels."}
              </p>
            )}
            <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
              <button
                onClick={() => setCancelModalOpen(false)}
                style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
              >
                Keep subscription
              </button>
              <button
                onClick={handleCancelConfirm}
                disabled={cancelling || refundEligibility === null}
                style={{
                  padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-critical)",
                  background: "var(--color-critical)", color: "var(--color-bg)",
                  cursor: cancelling ? "default" : "pointer", opacity: cancelling ? 0.6 : 1,
                }}
              >
                {cancelling ? "Working…" : "Confirm cancellation"}
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
            <a href="/dashboard/alerts" style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
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
          title="IAM Policy"
          sub="Attach this policy to the AWS IAM user whose credentials your Celery worker uses."
        />
        <IamPolicyGuide bucket={s3Bucket} />
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* WAF Configuration (Growth+ only), items 22/23                       */}
      {/* ------------------------------------------------------------------ */}
      {config && (config.tier === "growth" || config.tier === "pro") && (
      <section id="waf" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="WAF Configuration"
          sub="Push a block rule to your AWS WAF IP set when a high-confidence threat is detected."
        />
        <form onSubmit={handleSaveWaf}>
          <FieldRow label="WAF IP set ARN">
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
      {/* Cloudflare Configuration (Growth+ only), items 22/23                 */}
      {/* ------------------------------------------------------------------ */}
      {config && (config.tier === "growth" || config.tier === "pro") && (
      <section id="cloudflare" style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Cloudflare Configuration"
          sub="Push a block rule to your Cloudflare zone when a high-confidence threat is detected."
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

      {config && config.tier !== "growth" && config.tier !== "pro" && (
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Blocking Integrations"
          sub="Automatically push block rules to your WAF or Cloudflare zone when a high-confidence threat is detected."
        />
        <div style={{ border: "1px solid var(--color-border)", padding: "20px", background: "var(--color-surface)" }}>
          <p style={{ fontSize: "13px", color: "var(--color-text-muted)" }}>
            Available on Growth and Pro plans. Upgrade above to configure WAF and Cloudflare blocking.
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

      {/* ------------------------------------------------------------------ */}
      {/* Team Members (item 9)                                              */}
      {/* ------------------------------------------------------------------ */}
      <section style={{ marginBottom: "40px" }}>
        <SectionTitle
          title="Team Members"
          sub="Invite teammates to your organisation. Owners can change roles or remove members."
        />
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
          <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", padding: "24px", maxWidth: "460px", width: "90%" }}>
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
