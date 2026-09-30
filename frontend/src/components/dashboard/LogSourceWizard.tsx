"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";
import type { OrgConfigForOnboarding } from "@/components/dashboard/OnboardingModal";

// ---------------------------------------------------------------------------
// LogSourceWizard: the "connect your log source" onboarding step, one field
// (or one clearly-scoped action) at a time instead of a link out to the full
// Settings page. Covers both halves of that step: the S3 bucket/format/
// region fields, then the AWS IAM cross-account role that grants read
// access to them. Mirrors the same fields, endpoints, and copy as the
// Settings page's S3/AWS Access sections, just split into a guided sequence.
// ---------------------------------------------------------------------------

const AWS_REGIONS = [
  "us-east-1", "us-east-2", "us-west-1", "us-west-2",
  "eu-west-1", "eu-west-2", "eu-central-1",
  "ap-south-1", "ap-southeast-1", "ap-southeast-2", "ap-northeast-1",
];

type Step =
  | "bucket"
  | "format"
  | "region"
  | "externalId"
  | "trustPolicy"
  | "permissionsPolicy"
  | "roleArn"
  | "done";

const STEP_ORDER: Step[] = [
  "bucket", "format", "region", "externalId", "trustPolicy", "permissionsPolicy", "roleArn", "done",
];

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  fontSize: "13px",
  border: "1px solid var(--color-border)",
  background: "var(--color-surface)",
  color: "var(--color-text)",
  boxSizing: "border-box",
};

const selectStyle: React.CSSProperties = { ...inputStyle, cursor: "pointer" };

const preStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "10.5px",
  background: "var(--color-surface)",
  border: "1px solid var(--color-border)",
  margin: "10px 0",
  padding: "10px",
  whiteSpace: "pre-wrap",
  wordBreak: "break-all",
  color: "var(--color-text)",
  lineHeight: "1.5",
};

function WizardNav({
  onBack, onNext, nextLabel, nextDisabled, busy,
}: {
  onBack: (() => void) | null;
  onNext: (() => void) | null;
  nextLabel: string;
  nextDisabled?: boolean;
  busy?: boolean;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "16px" }}>
      {onBack ? (
        <button
          onClick={onBack}
          disabled={busy}
          style={{ padding: "6px 12px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: busy ? "default" : "pointer" }}
        >
          Back
        </button>
      ) : <span />}
      {onNext && (
        <button
          onClick={onNext}
          disabled={nextDisabled || busy}
          style={{
            padding: "6px 16px", fontSize: "12px", border: "1px solid var(--color-text)",
            background: "var(--color-text)", color: "var(--color-bg)",
            cursor: (nextDisabled || busy) ? "default" : "pointer",
            opacity: (nextDisabled || busy) ? 0.5 : 1,
          }}
        >
          {nextLabel}
        </button>
      )}
    </div>
  );
}

export function LogSourceWizard({
  config, setConfig, onExit, onSkipToSettings,
}: {
  config: OrgConfigForOnboarding | null;
  setConfig: (c: OrgConfigForOnboarding) => void;
  onExit: () => void;
  onSkipToSettings: () => void;
}) {
  // Resume where a returning admin left off rather than re-asking questions
  // already saved.
  const [step, setStep] = useState<Step>(() => {
    if (config?.s3_status === "connected") return "done";
    if (config?.s3_bucket && config?.log_format && config?.aws_region) return "externalId";
    return "bucket";
  });
  const [bucket, setBucket] = useState(config?.s3_bucket ?? "");
  const [prefix, setPrefix] = useState(config?.s3_prefix ?? "");
  const [format, setFormat] = useState(config?.log_format ?? "");
  const [region, setRegion] = useState(config?.aws_region ?? "");
  const [roleArn, setRoleArn] = useState(config?.aws_role_arn ?? "");
  const [includeBlocking, setIncludeBlocking] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [savingBasics, setSavingBasics] = useState(false);
  const [basicsError, setBasicsError] = useState<string | null>(null);
  const [savingRole, setSavingRole] = useState(false);
  const [roleResult, setRoleResult] = useState<{ status: string; message: string } | null>(null);

  const stepIndex = STEP_ORDER.indexOf(step);

  function copy(text: string, key: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(null), 2000);
    });
  }

  async function saveBasicsAndContinue() {
    setSavingBasics(true);
    setBasicsError(null);
    try {
      const r = await apiFetch(`/clients/me`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          s3_bucket: bucket || null,
          s3_prefix: prefix || null,
          log_format: format || null,
          aws_region: region || null,
        }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setBasicsError(typeof d?.detail === "string" ? d.detail : "Save failed.");
        return;
      }
      const updated: OrgConfigForOnboarding = await r.json();
      setConfig(updated);
      setStep("externalId");
    } catch {
      setBasicsError("Network error. Please try again.");
    } finally {
      setSavingBasics(false);
    }
  }

  async function saveRoleAndTest() {
    setSavingRole(true);
    setRoleResult(null);
    try {
      const r = await apiFetch(`/clients/me`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ aws_role_arn: roleArn || null }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setRoleResult({ status: "error", message: typeof d?.detail === "string" ? d.detail : "Save failed." });
        return;
      }
      const updated: OrgConfigForOnboarding = await r.json();
      setConfig(updated);
      if (updated.s3_status === "connected") {
        setRoleResult({ status: "connected", message: "Connected." });
      } else {
        setRoleResult({ status: "error", message: updated.s3_status_message ?? "Could not verify the connection yet." });
      }
    } catch {
      setRoleResult({ status: "error", message: "Network error. Please try again." });
    } finally {
      setSavingRole(false);
    }
  }

  const bucketName = bucket || "<YOUR-BUCKET-NAME>";
  const accountId = config?.clew_aws_account_id || "<CLEW_AWS_ACCOUNT_ID not yet configured>";
  const externalId = config?.aws_external_id ?? null;

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

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <button
          onClick={onExit}
          style={{ background: "none", border: "none", padding: 0, fontSize: "11px", color: "var(--color-text-muted)", cursor: "pointer", textDecoration: "underline" }}
        >
          ← Back to checklist
        </button>
        <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>Step {stepIndex + 1} of {STEP_ORDER.length}</span>
      </div>

      {step === "bucket" && (
        <div>
          <p style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 6px" }}>Where are your logs stored?</p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "10px" }}>
            The S3 bucket that holds your API Gateway or ALB access logs.
            Clew only ever reads from it, never writes.
          </p>
          <input
            type="text"
            value={bucket}
            onChange={e => setBucket(e.target.value)}
            placeholder="my-api-access-logs"
            style={inputStyle}
            autoFocus
          />
          <p style={{ fontSize: "11px", color: "var(--color-text-muted)", margin: "10px 0 4px" }}>
            Optional: a prefix, if your logs live in a subfolder of the bucket.
          </p>
          <input
            type="text"
            value={prefix}
            onChange={e => setPrefix(e.target.value)}
            placeholder="logs/ (optional)"
            style={inputStyle}
          />
          <WizardNav
            onBack={null}
            onNext={() => setStep("format")}
            nextLabel="Next"
            nextDisabled={!bucket.trim()}
          />
        </div>
      )}

      {step === "format" && (
        <div>
          <p style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 6px" }}>What format are they in?</p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "10px" }}>
            Pick whichever AWS service produced these logs. Clew parses each
            format differently, so this has to match exactly.
          </p>
          <select value={format} onChange={e => setFormat(e.target.value)} style={selectStyle} autoFocus>
            <option value="">— Select format —</option>
            <option value="apigw">API Gateway (apigw)</option>
            <option value="alb">Application Load Balancer (alb)</option>
          </select>
          <WizardNav
            onBack={() => setStep("bucket")}
            onNext={() => setStep("region")}
            nextLabel="Next"
            nextDisabled={!format}
          />
        </div>
      )}

      {step === "region" && (
        <div>
          <p style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 6px" }}>Which AWS region?</p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "10px" }}>
            The region your S3 bucket was created in, not necessarily the
            region most of your other infrastructure runs in.
          </p>
          <select value={region} onChange={e => setRegion(e.target.value)} style={selectStyle} autoFocus>
            <option value="">Select region</option>
            {AWS_REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          {basicsError && (
            <p style={{ fontSize: "12px", color: "var(--color-critical)", marginTop: "10px" }}>{basicsError}</p>
          )}
          <WizardNav
            onBack={() => setStep("format")}
            onNext={saveBasicsAndContinue}
            nextLabel={savingBasics ? "Saving…" : "Save & continue"}
            nextDisabled={!region}
            busy={savingBasics}
          />
        </div>
      )}

      {step === "externalId" && (
        <div>
          <p style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 6px" }}>Grant Clew read access</p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "10px" }}>
            Clew reads your logs by assuming an IAM role inside your own AWS
            account, never a long-lived access key. First, here is your
            organisation&apos;s External ID, a secret shared only between you
            and Clew, generated once and never shown anywhere public.
          </p>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <code style={{ fontFamily: "var(--font-mono)", fontSize: "12px", padding: "7px 10px", border: "1px solid var(--color-border)", background: "var(--color-surface)", flex: 1, wordBreak: "break-all" }}>
              {externalId || "Not yet generated"}
            </code>
            <button
              type="button"
              onClick={() => externalId && copy(externalId, "externalId")}
              disabled={!externalId}
              style={{ padding: "7px 10px", fontSize: "12px", border: "1px solid var(--color-border)", background: "var(--color-bg)", cursor: externalId ? "pointer" : "default" }}
            >
              {copied === "externalId" ? "Copied" : "Copy"}
            </button>
          </div>
          <WizardNav
            onBack={() => setStep("region")}
            onNext={() => setStep("trustPolicy")}
            nextLabel="Next"
          />
        </div>
      )}

      {step === "trustPolicy" && (
        <div>
          <p style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 6px" }}>Create the IAM role</p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "6px" }}>
            In your AWS account, create a new IAM role using this trust
            policy, it&apos;s what lets Clew&apos;s account assume the role,
            and only with your External ID above:
          </p>
          <pre style={preStyle}>{trustPolicy}</pre>
          <button
            type="button"
            onClick={() => copy(trustPolicy, "trust")}
            style={{ padding: "6px 12px", fontSize: "12px", border: "1px solid var(--color-border)", background: "var(--color-bg)", cursor: "pointer" }}
          >
            {copied === "trust" ? "Copied" : "Copy policy"}
          </button>
          <WizardNav
            onBack={() => setStep("externalId")}
            onNext={() => setStep("permissionsPolicy")}
            nextLabel="Next"
          />
        </div>
      )}

      {step === "permissionsPolicy" && (
        <div>
          <p style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 6px" }}>Attach the permissions policy</p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "6px" }}>
            Attach this permissions policy to that same role, it&apos;s what
            actually lets Clew read from your bucket:
          </p>
          <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "6px" }}>
            <input type="checkbox" checked={includeBlocking} onChange={e => setIncludeBlocking(e.target.checked)} />
            Also include WAF blocking permissions
          </label>
          <pre style={preStyle}>{permissionsPolicy}</pre>
          <button
            type="button"
            onClick={() => copy(permissionsPolicy, "permissions")}
            style={{ padding: "6px 12px", fontSize: "12px", border: "1px solid var(--color-border)", background: "var(--color-bg)", cursor: "pointer" }}
          >
            {copied === "permissions" ? "Copied" : "Copy policy"}
          </button>
          <WizardNav
            onBack={() => setStep("trustPolicy")}
            onNext={() => setStep("roleArn")}
            nextLabel="Next"
          />
        </div>
      )}

      {step === "roleArn" && (
        <div>
          <p style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 6px" }}>Paste your role ARN</p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "10px" }}>
            Once the role exists, copy its ARN from the AWS console and paste
            it here. Saving tests the connection immediately.
          </p>
          <input
            type="text"
            value={roleArn}
            onChange={e => setRoleArn(e.target.value)}
            placeholder="arn:aws:iam::123456789012:role/ClewAccessRole"
            style={inputStyle}
            autoFocus
          />
          {roleResult && (
            <p style={{ fontSize: "12px", marginTop: "10px", color: roleResult.status === "connected" ? "var(--color-low)" : "var(--color-critical)" }}>
              {roleResult.message}
            </p>
          )}
          <WizardNav
            onBack={() => setStep("permissionsPolicy")}
            onNext={roleResult?.status === "connected" ? () => setStep("done") : saveRoleAndTest}
            nextLabel={roleResult?.status === "connected" ? "Continue" : (savingRole ? "Testing…" : "Save & test")}
            nextDisabled={!roleArn.trim()}
            busy={savingRole}
          />
        </div>
      )}

      {step === "done" && (
        <div>
          <p style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 6px" }}>Your log source is connected</p>
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "14px" }}>
            Your first scan runs within 15 minutes. You can leave this
            checklist any time, it keeps updating in the background.
          </p>
          <WizardNav
            onBack={null}
            onNext={onExit}
            nextLabel="Back to checklist"
          />
        </div>
      )}

      <button
        onClick={onSkipToSettings}
        style={{ marginTop: "20px", background: "none", border: "none", padding: 0, fontSize: "11px", color: "var(--color-text-muted)", cursor: "pointer", textDecoration: "underline", alignSelf: "flex-start" }}
      >
        I&apos;d rather use the full Settings page
      </button>
    </div>
  );
}
