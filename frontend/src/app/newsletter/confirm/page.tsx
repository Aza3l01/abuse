"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { API_URL } from "@/lib/api";

function ConfirmBody() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [state, setState] = useState<"checking" | "done" | "error">("checking");
  const [message, setMessage] = useState("");
  // A missing token is known at render time, so it is derived, not set in an effect.
  const shownState = token ? state : "error";
  const shownMessage = token ? message : "This confirmation link is missing its token.";

  useEffect(() => {
    if (!token) return;
    fetch(`${API_URL}/newsletter/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (res) => {
        const d = await res.json().catch(() => ({}));
        if (!res.ok) {
          setState("error");
          setMessage(d?.detail ?? "Could not confirm your subscription.");
          return;
        }
        setState("done");
        setMessage(d?.message ?? "You're subscribed.");
      })
      .catch(() => {
        setState("error");
        setMessage("Network error. Please try again.");
      });
  }, [token]);

  return (
    <AuthLayout title="Newsletter subscription">
      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", lineHeight: 1.5 }}>
        {shownState === "checking" && "Confirming your subscription…"}
        {shownState !== "checking" && shownMessage}
      </p>
      {shownState !== "checking" && (
        <p style={{ fontSize: "13px", marginTop: "20px" }}>
          <Link href="/" style={{ color: "var(--color-text)" }}>Back to clewsec.com</Link>
        </p>
      )}
    </AuthLayout>
  );
}

export default function NewsletterConfirmPage() {
  return (
    <Suspense fallback={null}>
      <ConfirmBody />
    </Suspense>
  );
}
