"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { DataTable, ErrorLine, Section } from "@/components/internal/ui";
import { StaffApiError, formatMinor, staffRequest, type ReferralOverview, type Row } from "@/lib/staffApi";

const money = (r: Row) => formatMinor(r.amount_paise, r.currency);
const orgLink = (id: unknown, name: unknown) =>
  typeof id === "string" ? <Link href={`/orgs/${id}`}>{typeof name === "string" && name ? name : id}</Link> : "-";

export default function ReferralsPage() {
  const [view, setView] = useState<ReferralOverview | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    staffRequest<ReferralOverview>("/referrals?limit=200")
      .then((d) => {
        setView(d);
        setError("");
      })
      .catch((e) => setError(e instanceof StaffApiError ? e.message : "Failed to load."));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error && !view) return <ErrorLine message={error} />;
  if (!view) return <p style={{ fontSize: "13px" }}>Loading</p>;

  return (
    <div>
      <h1 style={{ fontSize: "18px", margin: "0 0 4px" }}>Referrals</h1>
      <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "0 0 12px" }}>
        Credits are revoked or approved from the referrer&apos;s account page. A fourth credit vesting for one referrer
        inside 30 days is held here until staff approve it.
      </p>

      <Section title="Held for review">
        <DataTable
          empty="Nothing is held."
          columns={[
            { key: "earned_at", label: "Earned" },
            { key: "org_name", label: "Referrer", render: (r) => orgLink(r.org_id, r.org_name) },
            { key: "source_org_name", label: "Referred org", render: (r) => orgLink(r.source_org_id, r.source_org_name) },
            { key: "amount_paise", label: "Amount", render: money },
            { key: "held_reason", label: "Why" },
          ]}
          rows={view.held}
        />
      </Section>

      <Section title="Referrers">
        <DataTable
          empty="No referrals yet."
          columns={[
            { key: "org_name", label: "Referrer", render: (r) => orgLink(r.org_id, r.org_name) },
            { key: "code", label: "Code" },
            { key: "signups", label: "Signups" },
            { key: "paying", label: "Paying" },
            { key: "pending", label: "Pending" },
            { key: "held", label: "Held" },
            { key: "available", label: "Available" },
            { key: "applied", label: "Applied" },
            { key: "revoked", label: "Revoked" },
            { key: "vested_30d", label: "Vested in 30 days" },
          ]}
          rows={view.referrers}
        />
      </Section>

      <Section title="Who referred whom">
        <DataTable
          empty="No referred signups."
          columns={[
            { key: "redeemed_at", label: "Signed up" },
            { key: "referee_name", label: "Referred org", render: (r) => orgLink(r.referee_org_id, r.referee_name) },
            { key: "referee_tier", label: "Tier" },
            { key: "referrer_name", label: "Referrer", render: (r) => orgLink(r.referrer_org_id, r.referrer_name) },
            { key: "code", label: "Code" },
            { key: "first_payment_confirmed_at", label: "First payment" },
            { key: "free_bill_applied", label: "Free bill used" },
            { key: "referee_deleted", label: "Deleted" },
          ]}
          rows={view.edges}
        />
      </Section>

      <Section title="Latest credits">
        <DataTable
          empty="No credits yet."
          columns={[
            { key: "earned_at", label: "Earned" },
            { key: "org_name", label: "Organisation", render: (r) => orgLink(r.org_id, r.org_name) },
            { key: "kind", label: "Kind" },
            { key: "status", label: "Status" },
            { key: "amount_paise", label: "Amount", render: money },
            { key: "vests_at", label: "Vested" },
            { key: "applied_at", label: "Applied" },
          ]}
          rows={view.recent}
        />
      </Section>
    </div>
  );
}
