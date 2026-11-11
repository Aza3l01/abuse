"use client";

import { useCallback, useEffect, useState } from "react";
import { DataTable, ErrorLine, Section, buttonStyle, inputStyle, secondaryButtonStyle } from "@/components/internal/ui";
import { CSV_EXPORT_URL, StaffApiError, formatMinor, staffRequest, type MetricsView, type Row } from "@/lib/staffApi";

function pct(value: Row[string]): string {
  return typeof value === "number" ? `${value}%` : "-";
}

const COMBINED_LABEL = "Combined";

const SOURCE_LABELS: Record<string, string> = {
  search_engine: "Search engine",
  llm: "LLM",
  social_forums: "Social media & forums",
  product_listings: "Product listings",
  word_of_mouth: "Word of mouth",
  direct_outreach: "Direct outreach",
  other: "Other",
  none: "No answer",
};

function amount(r: Row, key: string) {
  return <span style={{ whiteSpace: "nowrap" }}>{formatMinor(r[key], r.unit ?? r.currency)}</span>;
}

export default function MetricsPage() {
  const [view, setView] = useState<MetricsView | null>(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [entered, setEntered] = useState("");
  const [rateError, setRateError] = useState("");

  const load = useCallback((rate: string) => {
    const query = rate ? `?rate=${encodeURIComponent(rate)}` : "";
    staffRequest<MetricsView>(`/metrics${query}`)
      .then((v) => {
        setView(v);
        setEntered(rate);
        setRateError("");
      })
      .catch((e) => {
        if (e instanceof StaffApiError && e.status === 422) setRateError(e.message);
        else setError(e instanceof StaffApiError ? e.message : "Failed to load.");
      });
  }, []);

  useEffect(() => {
    load("");
  }, [load]);

  if (error) return <ErrorLine message={error} />;
  if (!view) return <p style={{ fontSize: "13px" }}>Loading</p>;

  function apply(event: React.FormEvent) {
    event.preventDefault();
    load(draft.trim());
  }

  // A combined row carries unit = INR. Amounts never wrap, the table scrolls instead.
  const money = (key: string) => (r: Row) => amount(r, key);

  const combinedReady = view.rate !== null && view.combined_current !== null && "mrr_minor" in view.combined_current;
  const combinedRow: Row[] = combinedReady
    ? [{ ...(view.combined_current as Row), currency: COMBINED_LABEL, unit: view.headline_currency }]
    : [];
  const withCombined = [...view.current, ...combinedRow];
  const combinedHistory = view.combined_history.map((r) => ({ ...r, unit: view.headline_currency }));

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
        <h1 style={{ fontSize: "18px", margin: 0 }}>Metrics</h1>
        <a
          href={entered ? `${CSV_EXPORT_URL}?rate=${encodeURIComponent(entered)}` : CSV_EXPORT_URL}
          style={{ ...secondaryButtonStyle, textDecoration: "none" }}
        >
          Export CSV
        </a>
      </div>
      <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "0 0 8px" }}>
        Computed live from the database. The INR and USD rows are exact and never altered. The Combined row adds USD to
        INR at a rate and is an approximate reporting figure, not accounting; check Razorpay for exact amounts. Churn
        and the other counts and percentages do not depend on the rate. Pilots are not paying customers. The month is
        the IST calendar month to date.
      </p>
      <form onSubmit={apply} style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px", margin: "0 0 8px" }}>
        <label htmlFor="rate" style={{ fontSize: "12px" }}>
          USD 1 = INR
        </label>
        <input
          id="rate"
          style={{ ...inputStyle, width: "96px" }}
          inputMode="decimal"
          placeholder={view.rate ?? "rate"}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" style={buttonStyle}>
          Apply
        </button>
        {entered && (
          <button
            type="button"
            style={secondaryButtonStyle}
            onClick={() => {
              setDraft("");
              load("");
            }}
          >
            Clear
          </button>
        )}
        {rateError && <span style={{ fontSize: "12px", color: "var(--color-critical)" }}>{rateError}</span>}
      </form>
      <p style={{ fontSize: "12px", margin: "0 0 8px" }}>
        {view.rate !== null ? (
          <>
            USD 1 = INR {view.rate},{" "}
            {view.rate_source === "entered"
              ? "rate entered on this page (INR per USD), applied to every date shown, not saved"
              : "default rate set on the server (INR per USD)"}
          </>
        ) : (
          <span style={{ color: "var(--color-critical)" }}>
            Combined: rate not set. Enter today&apos;s USD to INR rate above. INR and USD figures are unaffected.
          </span>
        )}
      </p>

      <Section title="Now, by currency and combined">
        <DataTable
          columns={[
            { key: "currency", label: "Currency" },
            { key: "paying_orgs", label: "Paying orgs" },
            { key: "mrr_minor", label: "MRR", render: money("mrr_minor") },
            { key: "arr_minor", label: "ARR", render: money("arr_minor") },
            { key: "arpa_minor", label: "ARPA", render: money("arpa_minor") },
            { key: "paying_basic", label: "Basic" },
            { key: "paying_growth", label: "Growth" },
            { key: "paying_pro", label: "Pro" },
            { key: "overdue_bills", label: "Overdue bills" },
            { key: "overdue_minor", label: "Overdue amount", render: money("overdue_minor") },
          ]}
          rows={withCombined}
        />
      </Section>

      <Section title="This month movement, by currency and combined">
        <DataTable
          columns={[
            { key: "currency", label: "Currency" },
            { key: "paying_orgs_start", label: "Orgs at start" },
            { key: "mrr_start_minor", label: "MRR at start", render: money("mrr_start_minor") },
            { key: "new_mrr_minor", label: "New", render: money("new_mrr_minor") },
            { key: "expansion_mrr_minor", label: "Expansion", render: money("expansion_mrr_minor") },
            { key: "contraction_mrr_minor", label: "Contraction", render: money("contraction_mrr_minor") },
            { key: "churned_mrr_minor", label: "Churned", render: money("churned_mrr_minor") },
            { key: "churned_orgs", label: "Churned orgs" },
            { key: "logo_churn_pct", label: "Logo churn", render: (r) => pct(r.logo_churn_pct) },
            { key: "revenue_churn_pct", label: "Revenue churn", render: (r) => pct(r.revenue_churn_pct) },
            { key: "refunds_count", label: "Refunds" },
            { key: "refunds_minor", label: "Refunded", render: money("refunds_minor") },
          ]}
          rows={withCombined}
        />
      </Section>

      <Section title="Users and pilots">
        <DataTable
          columns={[
            { key: "users_total", label: "Users" },
            { key: "users_verified", label: "Verified" },
            { key: "orgs_total", label: "Orgs" },
            { key: "active_pilots", label: "Active pilots" },
            { key: "pilots_converted", label: "Pilots paid" },
            { key: "pilots_expired_unpaid", label: "Pilots expired unpaid" },
            { key: "trial_to_paid_pct", label: "Trial to paid", render: (r) => pct(r.trial_to_paid_pct) },
          ]}
          rows={view.current.slice(0, 1)}
        />
      </Section>

      <Section title={`Signup sources, last ${view.signup_sources.window_days} days`}>
        <DataTable
          columns={[
            { key: "source", label: "Source", render: (r) => SOURCE_LABELS[String(r.source)] ?? String(r.source) },
            { key: "signups", label: "Signups" },
            { key: "paid", label: "Now paying" },
          ]}
          rows={view.signup_sources.rows}
        />
      </Section>

      <Section title="Recent answers for Other">
        <DataTable
          columns={[
            { key: "detail", label: "Answer" },
            { key: "created_at", label: "Signed up" },
            { key: "org_name", label: "Org", render: (r) => String(r.org_name ?? r.org_id ?? "-") },
          ]}
          rows={view.signup_sources.other_answers}
          empty="No answers yet."
        />
      </Section>

      <Section title="Daily history">
        <DataTable
          empty="No daily snapshots yet. The first one is written by the worker at 19:30 UTC."
          columns={[
            { key: "snapshot_date", label: "Date" },
            { key: "currency", label: "Currency" },
            { key: "users_total", label: "Users" },
            { key: "paying_orgs", label: "Paying orgs" },
            { key: "mrr_minor", label: "MRR", render: money("mrr_minor") },
            { key: "churned_mrr_minor", label: "Churned", render: money("churned_mrr_minor") },
            { key: "overdue_bills", label: "Overdue" },
          ]}
          rows={view.history}
        />
      </Section>

      <Section title="Daily history, combined">
        <DataTable
          empty="No daily snapshots yet."
          columns={[
            { key: "snapshot_date", label: "Date" },
            { key: "inr_per_usd", label: "Rate (INR per USD)", render: (r) => (r.inr_per_usd === null ? "not set" : String(r.inr_per_usd)) },
            { key: "paying_orgs", label: "Paying orgs" },
            { key: "mrr_minor", label: "MRR", render: money("mrr_minor") },
            { key: "churned_mrr_minor", label: "Churned", render: money("churned_mrr_minor") },
            { key: "overdue_bills", label: "Overdue" },
          ]}
          rows={combinedHistory}
        />
      </Section>
    </div>
  );
}
