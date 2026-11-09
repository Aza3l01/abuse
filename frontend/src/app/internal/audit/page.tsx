"use client";

import { useEffect, useState } from "react";
import { DataTable, ErrorLine } from "@/components/internal/ui";
import { StaffApiError, staffRequest, type Row } from "@/lib/staffApi";

export default function AuditPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    staffRequest<{ rows: Row[] }>("/audit?limit=200")
      .then((d) => setRows(d.rows))
      .catch((e) => setError(e instanceof StaffApiError ? e.message : "Failed to load."));
  }, []);

  if (error) return <ErrorLine message={error} />;
  if (!rows) return <p style={{ fontSize: "13px" }}>Loading</p>;

  return (
    <div>
      <h1 style={{ fontSize: "18px", margin: "0 0 12px" }}>Audit log</h1>
      <DataTable
        empty="No entries."
        columns={[
          { key: "created_at", label: "When" },
          { key: "staff_email", label: "Staff" },
          { key: "action", label: "Action" },
          { key: "org_name", label: "Organisation" },
          { key: "reason", label: "Reason" },
          { key: "ip", label: "IP" },
        ]}
        rows={rows}
      />
    </div>
  );
}
