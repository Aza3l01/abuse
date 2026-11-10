"use client";

import { useCallback, useEffect, useState, use } from "react";
import {
  ActionForm,
  DataTable,
  ErrorLine,
  KvTable,
  Section,
  buttonStyle,
  inputStyle,
} from "@/components/internal/ui";
import {
  StaffApiError,
  formatMinor,
  staffPost,
  staffRequest,
  type AccountView,
  type Row,
} from "@/lib/staffApi";

function RawView({ orgId }: { orgId: string }) {
  const [kind, setKind] = useState("verdicts");
  const [reason, setReason] = useState("");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setRows(null);
    setBusy(true);
    try {
      const data = await staffPost<{ rows: Row[] }>(`/orgs/${orgId}/raw`, { kind, reason, limit: 50 });
      setRows(data.rows);
    } catch (e) {
      setError(e instanceof StaffApiError ? e.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  const verdictColumns = ["timestamp", "ip", "method", "endpoint", "threat_type", "severity", "confidence", "blocked", "explanation"];
  const ipColumns = ["ip", "first_seen", "last_seen", "total_requests", "threat_count", "risk_score", "geo_country", "geo_asn_org", "waf_blocked", "cloudflare_blocked"];
  const keys = kind === "verdicts" ? verdictColumns : ipColumns;

  return (
    <div>
      <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "0 0 8px" }}>
        Raw customer rows (50 most recent). A reason is required and is written to the audit log before any data is shown.
      </p>
      <form onSubmit={load} style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginBottom: "12px" }}>
        <select style={inputStyle} value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="verdicts">Verdicts</option>
          <option value="ips">IP memory</option>
        </select>
        <input
          style={{ ...inputStyle, width: "360px" }}
          placeholder="Reason (min 10 characters)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <button type="submit" disabled={busy} style={buttonStyle}>
          Show raw data
        </button>
      </form>
      <ErrorLine message={error} />
      {rows && <DataTable empty="No rows." columns={keys.map((k) => ({ key: k, label: k }))} rows={rows} />}
    </div>
  );
}

export default function AccountPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [view, setView] = useState<AccountView | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setView(await staffRequest<AccountView>(`/orgs/${id}`));
      setError("");
    } catch (e) {
      setError(e instanceof StaffApiError ? e.message : "Failed to load.");
    }
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    staffRequest<AccountView>(`/orgs/${id}`)
      .then((data) => {
        if (!cancelled) setView(data);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof StaffApiError ? e.message : "Failed to load.");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error && !view) return <ErrorLine message={error} />;
  if (!view) return <p style={{ fontSize: "13px" }}>Loading</p>;

  const openBills = view.bills.filter((b) => b.status === "open");
  const money = (r: Row) => formatMinor(r.amount_paise, r.currency);
  const revocable = view.credits.filter((c) => c.status === "pending" || c.status === "held" || c.status === "available");
  const held = view.credits.filter((c) => c.status === "held");
  const creditOptions = (rows: Row[]) =>
    rows.length
      ? rows.map((c) => ({ value: String(c.id), label: `${c.status} ${money(c)} (${String(c.earned_at).slice(0, 10)})` }))
      : [{ value: "", label: "No credits" }];
  const deleted = view.org.deleted_at !== null;

  return (
    <div>
      <h1 style={{ fontSize: "18px", margin: "0 0 4px" }}>{String(view.org.company_name)}</h1>
      <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "0 0 12px", fontFamily: "var(--font-geist-mono), monospace" }}>
        {id}
      </p>

      <Section title="Account">
        <KvTable data={view.org} />
      </Section>
      <Section title="Usage">
        <KvTable data={view.usage} />
      </Section>
      <Section title="Onboarding and scanning">
        <KvTable data={{ ...view.onboarding, ...view.scan }} />
      </Section>
      <Section title="Billing">
        <KvTable data={view.billing} />
      </Section>
      <Section title="Trial and pilot">
        <KvTable data={view.trial} />
      </Section>
      <Section title="Referral">
        <KvTable data={view.referral} />
      </Section>
      <Section title="Credits">
        <DataTable
          empty="No credits."
          columns={[
            { key: "earned_at", label: "Earned" },
            { key: "kind", label: "Kind" },
            { key: "status", label: "Status" },
            { key: "amount_paise", label: "Amount", render: money },
            { key: "source_org_id", label: "From org" },
            { key: "vests_at", label: "Vested" },
            { key: "held_reason", label: "Held because" },
            { key: "applied_bill_id", label: "Applied to bill" },
            { key: "revoked_reason", label: "Revoked because" },
          ]}
          rows={view.credits}
        />
      </Section>
      <Section title="Members">
        <DataTable
          columns={[
            { key: "email", label: "Email" },
            { key: "full_name", label: "Name" },
            { key: "role", label: "Role" },
            { key: "is_billing_contact", label: "Billing contact" },
            { key: "email_verified", label: "Verified" },
            { key: "mfa_enabled", label: "MFA" },
          ]}
          rows={view.members}
        />
      </Section>
      <Section title="Bills">
        <DataTable
          columns={[
            { key: "id", label: "Id" },
            { key: "period_start", label: "Issued" },
            { key: "due_date", label: "Due" },
            { key: "cancel_on", label: "Cancels on" },
            { key: "tier", label: "Tier" },
            { key: "period", label: "Period" },
            { key: "amount_paise", label: "Amount due", render: money },
            { key: "credit_applied_paise", label: "Credit applied", render: (r) => formatMinor(r.credit_applied_paise, r.currency) },
            { key: "status", label: "Status" },
            { key: "paid_at", label: "Paid" },
          ]}
          rows={view.bills}
        />
      </Section>
      <Section title="Payments">
        <DataTable
          columns={[
            { key: "created_at", label: "Created" },
            { key: "purpose", label: "Purpose" },
            { key: "status", label: "Status" },
            { key: "amount_paise", label: "Amount", render: money },
            { key: "razorpay_order_id", label: "Order" },
            { key: "razorpay_payment_id", label: "Payment" },
            { key: "manual", label: "Manual" },
            { key: "reference", label: "Reference" },
          ]}
          rows={view.payments}
        />
      </Section>
      <Section title="Billing events">
        <DataTable
          columns={[
            { key: "created_at", label: "When" },
            { key: "event", label: "Event" },
            { key: "from_tier", label: "From" },
            { key: "to_tier", label: "To" },
            { key: "period", label: "Period" },
            { key: "amount_paise", label: "Amount", render: money },
          ]}
          rows={view.events}
        />
      </Section>

      <Section title="Billing actions">
        {deleted && <p style={{ fontSize: "13px" }}>This account is deleted. Actions are disabled.</p>}
        {!deleted && (
          <>
            <ActionForm
              title="Mark a bill paid (bank transfer received)"
              help="Records a manual payment, closes the bill and issues the receipt, exactly like an online payment."
              path={`/orgs/${id}/bills/mark-paid`}
              fields={[
                {
                  name: "bill_id",
                  label: "Open bill",
                  kind: "select",
                  options: openBills.length
                    ? openBills.map((b) => ({ value: String(b.id), label: `${b.period_start} ${money(b)}` }))
                    : [{ value: "", label: "No open bills" }],
                },
                { name: "reference", label: "Bank reference", kind: "text" },
              ]}
              onDone={load}
            />
            <ActionForm
              title="Void a bill"
              help="Cancels an open bill without payment."
              path={`/orgs/${id}/bills/void`}
              fields={[
                {
                  name: "bill_id",
                  label: "Open bill",
                  kind: "select",
                  options: openBills.length
                    ? openBills.map((b) => ({ value: String(b.id), label: `${b.period_start} ${money(b)}` }))
                    : [{ value: "", label: "No open bills" }],
                },
              ]}
              onDone={load}
            />
            <ActionForm
              title="Extend the paid period"
              help="Moves the next bill date forward by whole months. Only with no open bill."
              path={`/orgs/${id}/extend-period`}
              fields={[{ name: "months", label: "Months (1 to 12)", kind: "number", initial: "1" }]}
              onDone={load}
            />
            <ActionForm
              title="Pause the non-payment downgrade"
              help="Moves the cancel date of every open bill later."
              path={`/orgs/${id}/pause-downgrade`}
              fields={[{ name: "days", label: "Days (1 to 30)", kind: "number", initial: "14" }]}
              onDone={load}
            />
            <ActionForm
              title="Reinstate after non-payment (bank transfer received)"
              help="For an account downgraded for non-payment. Records the transfer for the restore amount and restores the plan."
              path={`/orgs/${id}/reinstate`}
              fields={[
                {
                  name: "tier",
                  label: "Tier",
                  kind: "select",
                  options: [
                    { value: "basic", label: "basic" },
                    { value: "growth", label: "growth" },
                    { value: "pro", label: "pro" },
                  ],
                },
                {
                  name: "period",
                  label: "Period",
                  kind: "select",
                  options: [
                    { value: "monthly", label: "monthly" },
                    { value: "annual", label: "annual" },
                  ],
                },
                { name: "reference", label: "Bank reference", kind: "text" },
              ]}
              onDone={load}
            />
            <ActionForm
              title="Extend the pilot"
              help="Pilot accounts only. Adds days to the pilot end and re-arms the reminder emails."
              path={`/orgs/${id}/extend-pilot`}
              fields={[{ name: "days", label: "Days (1 to 90)", kind: "number", initial: "14" }]}
              onDone={load}
            />
            <ActionForm
              title="Revoke a referral credit"
              help="Cancels a credit that has not been used on a bill (pending, held or available). A used credit cannot be revoked."
              path={(values) => `/referrals/credits/${encodeURIComponent(values.credit_id)}/revoke`}
              fields={[{ name: "credit_id", label: "Credit", kind: "select", options: creditOptions(revocable) }]}
              onDone={load}
            />
            <ActionForm
              title="Approve a held referral credit"
              help="Releases a credit held for review (more than 3 vested in 30 days). It becomes available at once."
              path={(values) => `/referrals/credits/${encodeURIComponent(values.credit_id)}/approve`}
              fields={[{ name: "credit_id", label: "Held credit", kind: "select", options: creditOptions(held) }]}
              onDone={load}
            />
          </>
        )}
      </Section>

      <Section title="Raw customer data">
        <RawView orgId={id} />
      </Section>

      <Section title="Staff actions on this account">
        <DataTable
          empty="No staff actions yet."
          columns={[
            { key: "created_at", label: "When" },
            { key: "staff_email", label: "Staff" },
            { key: "action", label: "Action" },
            { key: "reason", label: "Reason" },
          ]}
          rows={view.audit}
        />
      </Section>
    </div>
  );
}
