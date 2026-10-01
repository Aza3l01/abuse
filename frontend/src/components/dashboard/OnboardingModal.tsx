"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { onOnboardingOpenRequested, setOnboardingPanelWidth } from "@/lib/onboarding";
import { LogSourceWizard } from "@/components/dashboard/LogSourceWizard";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface OrgRow {
  id: string;
  role: string;
  active: boolean;
}

interface SummaryOnboarding {
  onboarding_completed_at: string | null;
  onboarding_dismissed_at: string | null;
}

export interface OrgConfigForOnboarding {
  tier: string;
  s3_bucket: string | null;
  s3_prefix: string | null;
  log_format: string | null;
  aws_region: string | null;
  s3_status: string | null;
  s3_status_message: string | null;
  home_country: string | null;
  alert_email: string | null;
  waf_ip_set_id: string | null;
  cloudflare_zone_id: string | null;
  aws_role_arn: string | null;
  aws_external_id: string | null;
  clew_aws_account_id: string | null;
  onboarding_completed_at: string | null;
  onboarding_dismissed_at: string | null;
}

type Stage = "hidden" | "panel" | "minimized";

const PANEL_WIDTH = 380;
const POLL_MS = 6000;

// ---------------------------------------------------------------------------
// Small presentational pieces
// ---------------------------------------------------------------------------

function StepIcon({ done }: { done: boolean }) {
  return (
    <div style={{
      width: "14px",
      height: "14px",
      flexShrink: 0,
      marginTop: "2px",
      border: "1px solid var(--color-text)",
      background: done ? "var(--color-text)" : "transparent",
      transition: "background 150ms ease",
    }} />
  );
}

function StepRow({
  done, next, label, sub, status, ctaLabel, onAction,
}: {
  done: boolean;
  next: boolean;
  label: string;
  sub?: string;
  status?: string;
  ctaLabel: string;
  onAction: () => void;
}) {
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: "10px", padding: "12px 10px",
      margin: "0 -10px", borderBottom: "1px solid var(--color-border)",
      borderLeft: next ? "3px solid var(--color-text)" : "3px solid transparent",
      background: next ? "var(--color-surface)" : "transparent",
      transition: "background 200ms ease, border-color 200ms ease",
    }}>
      <StepIcon done={done} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ fontSize: "13px", fontWeight: 600, margin: 0, display: "flex", alignItems: "center", gap: "6px" }}>
          {label}
          {next && <span style={{ fontSize: "10px", fontWeight: 700, color: "var(--color-text-muted)" }}>NEXT</span>}
        </p>
        {sub && <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "3px 0 0" }}>{sub}</p>}
        {status && <p style={{ fontSize: "11px", color: "var(--color-text-muted)", margin: "4px 0 0" }}>{status}</p>}
      </div>
      <button
        onClick={onAction}
        style={{
          flexShrink: 0,
          padding: "5px 12px",
          fontSize: "12px",
          border: "1px solid var(--color-border)",
          background: "transparent",
          color: "var(--color-text)",
          cursor: "pointer",
        }}
      >
        {ctaLabel}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Guided onboarding. State lives on the Organization
 * (onboarding_completed_at/onboarding_dismissed_at), progress per step is
 * derived from live org config, never stored separately. Mounted once in
 * dashboard/layout.tsx as a persistent right-docked panel, not a modal that
 * disappears on navigation: DashboardContentShell reserves margin for it via
 * lib/onboarding.ts's panel-width event. "Minimize" collapses it to a small
 * reopenable chip without dismissing it; only the explicit "don't show
 * again" link marks onboarding_dismissed_at.
 */
export function OnboardingModal() {
  const router = useRouter();

  const [role, setRole] = useState<string | null>(null);
  const [onboarding, setOnboarding] = useState<SummaryOnboarding | null>(null);
  const [stage, setStage] = useState<Stage>("hidden");
  const [config, setConfig] = useState<OrgConfigForOnboarding | null>(null);
  const [busy, setBusy] = useState(false);
  // Which step is currently expanded into its own guided sub-flow inline in
  // the panel, instead of just linking out to Settings. Only "s3" uses this
  // today (see LogSourceWizard), the other steps still just navigate.
  const [activeWizard, setActiveWizard] = useState<"s3" | null>(null);

  // Load role + onboarding state once. Auto-opens for an owner/admin whose
  // org has never been dismissed or completed.
  useEffect(() => {
    Promise.all([
      apiFetch(`/auth/orgs`).then(r => r.ok ? r.json() : []).catch(() => [] as OrgRow[]),
      apiFetch(`/dashboard/summary?days=7`).then(r => r.ok ? r.json() : null).catch(() => null),
    ]).then(([orgs, summary]: [OrgRow[], SummaryOnboarding | null]) => {
      const active = orgs.find(o => o.active) ?? orgs[0];
      setRole(active?.role ?? null);
      if (summary) {
        setOnboarding({
          onboarding_completed_at: summary.onboarding_completed_at,
          onboarding_dismissed_at: summary.onboarding_dismissed_at,
        });
        const isOwnerOrAdmin = active?.role === "owner" || active?.role === "admin";
        if (isOwnerOrAdmin && !summary.onboarding_completed_at && !summary.onboarding_dismissed_at) {
          setStage("panel");
        }
      }
    });
  }, []);

  // Manual reopen, e.g. the "Guided onboarding" button. No-op for a viewer,
  // who can't complete any step here.
  useEffect(() => {
    return onOnboardingOpenRequested(() => {
      if (role === "owner" || role === "admin") setStage("panel");
    });
  }, [role]);

  // Reserve right-margin on the page content only while fully docked, not
  // while minimized to the chip or hidden entirely.
  useEffect(() => {
    setOnboardingPanelWidth(stage === "panel" ? PANEL_WIDTH : 0);
    return () => setOnboardingPanelWidth(0);
  }, [stage]);

  // Poll live org config while the panel is docked or minimized, so a step
  // saved on the Settings page (which now stays mounted alongside the
  // panel, no more navigate-away-and-lose-it) checks itself off without
  // needing a manual reopen. Backs off to a slower interval once minimized
  // (the user isn't watching it) and stops entirely once onboarding is
  // actually complete, instead of polling every 6s indefinitely either way.
  useEffect(() => {
    if (stage === "hidden" || (role !== "owner" && role !== "admin")) return;
    if (config?.onboarding_completed_at) return;
    let cancelled = false;
    function refresh() {
      apiFetch(`/clients/me`)
        .then(r => r.ok ? r.json() : null)
        .then((c: OrgConfigForOnboarding | null) => { if (!cancelled && c) setConfig(c); })
        .catch(() => {/* panel still usable without the derived checkmarks */});
    }
    refresh();
    const intervalMs = stage === "minimized" ? POLL_MS * 5 : POLL_MS;
    const id = setInterval(refresh, intervalMs);
    return () => { cancelled = true; clearInterval(id); };
  }, [stage, role, config?.onboarding_completed_at]);

  async function handleDismiss() {
    setBusy(true);
    try {
      const r = await apiFetch(`/clients/me/onboarding/dismiss`, { method: "POST" });
      if (r.ok) {
        const updated = await r.json();
        setOnboarding({
          onboarding_completed_at: updated.onboarding_completed_at,
          onboarding_dismissed_at: updated.onboarding_dismissed_at,
        });
      }
    } finally {
      setBusy(false);
      setStage("hidden");
    }
  }

  async function handleComplete() {
    setBusy(true);
    try {
      const r = await apiFetch(`/clients/me/onboarding/complete`, { method: "POST" });
      if (r.ok) {
        const updated = await r.json();
        setOnboarding({
          onboarding_completed_at: updated.onboarding_completed_at,
          onboarding_dismissed_at: updated.onboarding_dismissed_at,
        });
      }
    } finally {
      setBusy(false);
      setStage("hidden");
    }
  }

  // Navigates only, the panel stays docked so progress ticks off next to
  // the form instead of disappearing the moment they click a step.
  function goTo(anchor: string) {
    router.push(`/dashboard/settings${anchor}`);
  }

  // Viewer, org not yet onboarded: a plain note, never a wizard it can't act on.
  if (role === "viewer" && onboarding && !onboarding.onboarding_completed_at) {
    return (
      <div style={{ padding: "8px 32px", fontSize: "12px", color: "var(--color-text-muted)" }}>
        Your administrator is still setting this workspace up.
      </div>
    );
  }

  if (stage === "hidden") return null;

  const s3Done = !!(config?.s3_bucket && config?.log_format) && config?.s3_status !== "error";
  const s3Status = config?.s3_status === "connected"
    ? "Connected"
    : config?.s3_status === "error"
    ? `Error: ${config?.s3_status_message ?? "connection failed"}`
    : config?.s3_bucket
    ? "Saved, not yet tested"
    : "Not configured yet";
  const countryDone = !!config?.home_country;
  const isFree = config?.tier === "free";
  const alertsDone = !!config?.alert_email;
  const blockingDone = !!(config?.waf_ip_set_id || config?.cloudflare_zone_id);

  // Only the actionable rows count toward progress and the "next" pointer,
  // the free-tier alerts row is a paywall notice, not a step someone can
  // check off, so it's excluded from both.
  const progressSteps: { key: string; done: boolean }[] = [
    { key: "s3", done: s3Done },
    { key: "country", done: countryDone },
    ...(!isFree ? [{ key: "alerts", done: alertsDone }] : []),
    ...(!isFree ? [{ key: "blocking", done: blockingDone }] : []),
  ];
  const doneCount = progressSteps.filter(s => s.done).length;
  const totalCount = progressSteps.length;
  const nextKey = progressSteps.find(s => !s.done)?.key ?? null;
  const allDone = nextKey === null;

  return (
    <>
      {/* Minimized chip: reopens the docked panel without touching dismissed/completed state. */}
      <button
        onClick={() => setStage("panel")}
        style={{
          position: "fixed", bottom: "20px", right: "20px", zIndex: 90,
          display: stage === "minimized" ? "flex" : "none",
          alignItems: "center", gap: "8px",
          padding: "10px 16px", fontSize: "12px", fontWeight: 600,
          background: "var(--color-text)", color: "var(--color-bg)",
          border: "1px solid var(--color-text)", cursor: "pointer",
        }}
      >
        Setup {doneCount}/{totalCount}
      </button>

      {/* Docked panel: stays mounted across dashboard pages, slides off-screen (not
          unmounted) when minimized so its own polling and scroll position persist. */}
      <div
        style={{
          position: "fixed", top: 0, right: 0, bottom: 0, width: `${PANEL_WIDTH}px`, maxWidth: "92vw",
          background: "var(--color-bg)", borderLeft: "1px solid var(--color-border)",
          zIndex: 95, display: "flex", flexDirection: "column", overflowY: "auto",
          padding: "24px 20px",
          transform: stage === "panel" ? "translateX(0)" : "translateX(100%)",
          visibility: stage === "panel" ? "visible" : "hidden",
          transition: "transform 240ms ease",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "4px" }}>
          <p style={{ fontSize: "16px", fontWeight: 700, margin: 0 }}>Get started with Clew</p>
          <button
            onClick={() => setStage("minimized")}
            aria-label="Minimize"
            title="Minimize"
            style={{ background: "none", border: "none", cursor: "pointer", fontSize: "16px", color: "var(--color-text-muted)", padding: 0, lineHeight: 1 }}
          >
            ×
          </button>
        </div>
        <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "16px" }}>
          A few steps to get real detections flowing. Minimize this any time,
          your progress keeps updating in the background.
        </p>

        <div style={{ marginBottom: "12px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "var(--color-text-muted)", marginBottom: "4px" }}>
            <span>Setup progress</span>
            <span>{doneCount} of {totalCount}</span>
          </div>
          <div style={{ height: "4px", background: "var(--color-border)", width: "100%" }}>
            <div style={{
              height: "100%", background: "var(--color-text)",
              width: `${totalCount ? (doneCount / totalCount) * 100 : 0}%`,
              transition: "width 240ms ease",
            }} />
          </div>
        </div>

        {activeWizard === "s3" ? (
          <LogSourceWizard
            config={config}
            setConfig={setConfig}
            onExit={() => setActiveWizard(null)}
            onSkipToSettings={() => { setActiveWizard(null); goTo("#s3"); }}
          />
        ) : (
          <>
            <StepRow
              done={s3Done}
              next={nextKey === "s3"}
              label="Connect your log source"
              sub="Point Clew at your API Gateway or ALB access logs in S3. This is what the detection engine actually scans, nothing else here works without it."
              status={s3Status}
              ctaLabel="Configure"
              onAction={() => setActiveWizard("s3")}
            />
            <StepRow
              done={countryDone}
              next={nextKey === "country"}
              label="Set your home country"
              sub="Helps detection tell normal traffic from an unusual foreign spike. Used as a baseline signal only, never a hard block on its own."
              ctaLabel="Configure"
              onAction={() => goTo("#s3")}
            />
            {isFree ? (
              <div style={{ display: "flex", alignItems: "flex-start", gap: "10px", padding: "12px 0", borderBottom: "1px solid var(--color-border)" }}>
                <div style={{ width: "14px", flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: "13px", fontWeight: 600, margin: 0, color: "var(--color-text-muted)" }}>Choose where alerts go</p>
                  <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "2px 0 0" }}>
                    Email alerts on critical threats require a paid plan.
                  </p>
                </div>
                <button
                  onClick={() => goTo("#billing")}
                  style={{ flexShrink: 0, padding: "5px 12px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
                >
                  Upgrade
                </button>
              </div>
            ) : (
              <StepRow
                done={alertsDone}
                next={nextKey === "alerts"}
                label="Choose where alerts go"
                sub="Email address and severity threshold for critical-threat alerts, so you hear about a threat before deciding what to do about it."
                ctaLabel="Configure"
                onAction={() => goTo("#alerts")}
              />
            )}
            {!isFree && (
              <StepRow
                done={blockingDone}
                next={nextKey === "blocking"}
                label="Set up blocking (optional)"
                sub="Automatically or manually block malicious IPs via AWS WAF or Cloudflare. Skip this if you only want visibility for now, it's not required."
                ctaLabel="Configure"
                onAction={() => goTo("#waf")}
              />
            )}

            <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "16px 0 4px" }}>
              {allDone
                ? "Every step is complete. Click Finish setup below whenever you're ready."
                : "Once your log source is connected, your first scan runs within 15 minutes."}
            </p>
          </>
        )}

        <div style={{ marginTop: "auto", paddingTop: "16px" }}>
          <button
            onClick={handleDismiss}
            disabled={busy}
            style={{
              display: "block", background: "none", border: "none", padding: 0,
              fontSize: "11px", color: "var(--color-text-muted)", textDecoration: "underline",
              cursor: busy ? "default" : "pointer", marginBottom: "12px",
            }}
          >
            Don&apos;t show this automatically again
          </button>
          <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
            <button
              onClick={() => setStage("minimized")}
              disabled={busy}
              style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: busy ? "default" : "pointer" }}
            >
              Remind me later
            </button>
            <button
              onClick={handleComplete}
              disabled={busy}
              style={{
                padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-text)",
                background: "var(--color-text)", color: "var(--color-bg)",
                cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
              }}
            >
              Finish setup
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
