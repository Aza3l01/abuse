"use client";

import Link from "next/link";
import { useState } from "react";
import { DataTable, ErrorLine, buttonStyle, inputStyle } from "@/components/internal/ui";
import { StaffApiError, staffRequest, type OrgSummary } from "@/lib/staffApi";

export default function InternalHome() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<OrgSummary[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const data = await staffRequest<{ results: OrgSummary[] }>(`/orgs/search?q=${encodeURIComponent(query.trim())}`);
      setResults(data.results);
    } catch (e) {
      setError(e instanceof StaffApiError ? e.message : "Search failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: "18px", margin: "0 0 12px" }}>Find an account</h1>
      <form onSubmit={search} style={{ display: "flex", gap: "8px", marginBottom: "16px" }}>
        <input
          style={{ ...inputStyle, width: "360px" }}
          placeholder="Owner or member email, org name, or org id"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit" disabled={busy || query.trim().length < 2} style={buttonStyle}>
          Search
        </button>
      </form>
      <ErrorLine message={error} />
      {results && (
        <DataTable
          empty="No matching accounts."
          columns={[
            {
              key: "company_name",
              label: "Organisation",
              render: (r) => <Link href={`/orgs/${r.id}`}>{String(r.company_name)}</Link>,
            },
            { key: "owner_email", label: "Owner" },
            { key: "tier", label: "Tier" },
            { key: "billing_provider", label: "Billing" },
            { key: "created_at", label: "Created" },
            { key: "deleted", label: "Deleted" },
          ]}
          rows={results.map((r) => ({ ...r }))}
        />
      )}
    </div>
  );
}
