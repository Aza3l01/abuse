"use client";

import { useEffect, useState } from "react";
import { DataTable, ErrorLine, Section } from "@/components/internal/ui";
import { StaffApiError, formatMinor, staffRequest, type HealthView, type Row } from "@/lib/staffApi";

export default function HealthPage() {
  const [view, setView] = useState<HealthView | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    staffRequest<HealthView>("/health")
      .then(setView)
      .catch((e) => setError(e instanceof StaffApiError ? e.message : "Failed to load."));
  }, []);

  if (error) return <ErrorLine message={error} />;
  if (!view) return <p style={{ fontSize: "13px" }}>Loading</p>;

  const money = (r: Row) => formatMinor(r.amount_paise, r.currency);
  const paymentColumns = [
    { key: "created_at", label: "Created" },
    { key: "org_name", label: "Organisation" },
    { key: "purpose", label: "Purpose" },
    { key: "amount_paise", label: "Amount", render: money },
    { key: "razorpay_order_id", label: "Order" },
  ];

  return (
    <div>
      <h1 style={{ fontSize: "18px", margin: "0 0 12px" }}>System health</h1>

      <Section title="Scheduled tasks (last run)">
        {!view.task_runs_recorded && (
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "0 0 8px" }}>
            No runs recorded yet. Tracking starts when the worker restarts after this release.
          </p>
        )}
        <DataTable
          columns={[
            { key: "name", label: "Task" },
            { key: "last_run_at", label: "Last run" },
            { key: "state", label: "State" },
            { key: "last_success_at", label: "Last success" },
          ]}
          rows={view.tasks}
        />
      </Section>

      <Section title="Payment reconciliation (Razorpay against local payments, last 48 hours)">
        {view.reconciliation ? (
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "0 0 8px" }}>
            Last run {view.reconciliation.ran_at}. {view.reconciliation.checked} payments checked,{" "}
            {view.reconciliation.discrepancies.length} differences.
          </p>
        ) : (
          <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "0 0 8px" }}>
            Has not run yet.
          </p>
        )}
        <DataTable
          empty="No differences."
          columns={[
            { key: "kind", label: "Kind" },
            { key: "org_name", label: "Organisation" },
            { key: "amount_paise", label: "Amount", render: money },
            { key: "razorpay_payment_id", label: "Razorpay payment" },
            { key: "razorpay_order_id", label: "Order" },
            { key: "detail", label: "Detail" },
          ]}
          rows={view.reconciliation?.discrepancies ?? []}
        />
      </Section>

      <Section title="Failed payments">
        <DataTable empty="None." columns={paymentColumns} rows={view.failed_payments} />
      </Section>
      <Section title="Payments stuck in created for more than 2 hours">
        <DataTable empty="None." columns={paymentColumns} rows={view.stuck_payments} />
      </Section>
      <Section title="Recent webhook events processed">
        <DataTable
          empty="None."
          columns={[
            { key: "created_at", label: "Processed" },
            { key: "provider", label: "Provider" },
            { key: "event_id", label: "Event id" },
          ]}
          rows={view.recent_webhook_events}
        />
      </Section>
      <Section title="LLM and request usage this month">
        <DataTable
          empty="None."
          columns={[
            { key: "company_name", label: "Organisation" },
            { key: "tier", label: "Tier" },
            { key: "monthly_llm_calls", label: "LLM calls" },
            { key: "monthly_llm_cap", label: "LLM cap" },
            { key: "monthly_requests_processed", label: "Requests" },
          ]}
          rows={view.llm_usage}
        />
      </Section>
    </div>
  );
}
