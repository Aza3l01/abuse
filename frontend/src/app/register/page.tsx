"use client";

import { useState, useRef, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { AuthLayout, inputStyle, labelStyle, primaryBtnStyle } from "@/components/auth/AuthLayout";
import { Turnstile } from "@/components/auth/Turnstile";
import { API_URL } from "@/lib/api";
import { SITE_URL } from "@/lib/urls";
import { track } from "@/lib/analytics";
import { passwordStrength, passwordStrengthLabel } from "@/lib/passwordStrength";

// Phase 4b: plans that can actually be checked out self-serve. Never "starter"
// (that's the no-plan default, not a chosen upgrade) and never "enterprise"
// (contact-only, no self-serve checkout exists for it).
const PURCHASABLE_PLANS = ["basic", "growth", "pro"];

// Phase 12b: "How did you hear about us". Values match SIGNUP_SOURCES in
// api/routes/org.py. Optional, and free text is only ever collected for "other".
const SIGNUP_SOURCE_OPTIONS: { value: string; label: string }[] = [
  { value: "search_engine",   label: "Search engine" },
  { value: "llm",             label: "LLM" },
  { value: "social_forums",   label: "Social media & forums" },
  { value: "product_listings", label: "Product listings" },
  { value: "word_of_mouth",   label: "Word of mouth" },
  { value: "direct_outreach", label: "Direct outreach" },
  { value: "other",           label: "Other" },
];

function RegisterForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const planParam = searchParams.get("plan");
  const validPlan = planParam && PURCHASABLE_PLANS.includes(planParam) ? planParam : null;

  const [fullName,    setFullName]    = useState("");
  const [email,       setEmail]       = useState("");
  const [password,    setPassword]    = useState("");
  const [company,     setCompany]     = useState("");
  // TODO.md priority item 5: a referral invite link carries ?ref=<code>,
  // prefilling the same dual-purpose code field pilot codes already use.
  const [pilotCode,   setPilotCode]   = useState(searchParams.get("ref") ?? "");
  const [signupSource, setSignupSource] = useState("");
  const [signupSourceDetail, setSignupSourceDetail] = useState("");
  const [tosAccepted, setTosAccepted] = useState(false);
  const [captchaToken, setCaptchaToken] = useState("");
  const [error,       setError]       = useState("");
  const [loading,     setLoading]     = useState(false);
  const [registered,  setRegistered]  = useState(false);
  // Phase 12: advice only, the server checks the code again at registration.
  const [codeCheck, setCodeCheck] = useState<{ code: string; valid: boolean; kind: string | null } | null>(null);
  const startedRef = useRef(false);

  async function checkCode(raw: string) {
    const code = raw.trim();
    if (!code) return;
    try {
      const res = await fetch(`${API_URL}/auth/validate-code?code=${encodeURIComponent(code)}`);
      if (!res.ok) return;
      const data = await res.json();
      setCodeCheck({ code, valid: !!data.valid, kind: data.kind ?? null });
    } catch {
      /* the check is optional, registration validates the code itself */
    }
  }

  useEffect(() => {
    const prefilled = (searchParams.get("ref") ?? "").trim();
    if (!prefilled) return;
    let cancelled = false;
    fetch(`${API_URL}/auth/validate-code?code=${encodeURIComponent(prefilled)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data) setCodeCheck({ code: prefilled, valid: !!data.valid, kind: data.kind ?? null });
      })
      .catch(() => { /* the check is optional, registration validates the code itself */ });
    return () => { cancelled = true; };
  }, [searchParams]);

  // Funnel step "registration started": the first time any field is touched.
  function handleFormFocus() {
    if (startedRef.current) return;
    startedRef.current = true;
    track("registration_started", { plan: validPlan });
  }

  const strength = passwordStrength(password);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!tosAccepted) {
      setError("You must agree to the Terms of Service and Privacy Policy.");
      return;
    }
    if (!captchaToken) {
      setError("Please complete the CAPTCHA.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/auth/register`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          full_name: fullName,
          company_name: company,
          pilot_code: pilotCode || null,
          captcha_token: captchaToken,
          tos_accepted: tosAccepted,
          signup_source: signupSource || null,
          signup_source_detail: signupSource === "other" && signupSourceDetail.trim() ? signupSourceDetail.trim() : null,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Registration failed.");
        return;
      }
      // Phase 4b: an intent, not an entitlement, read by the dashboard once
      // to trigger checkout, then cleared. Never persisted to the Organization.
      if (validPlan) {
        try { sessionStorage.setItem("clew_plan", validPlan); } catch { /* storage unavailable, plan is skipped */ }
      }
      track("registration_completed", { plan: validPlan, has_referral: pilotCode !== "", signup_source: signupSource || null });
      setRegistered(true);
    } catch {
      setError("Could not connect to the server. Try again.");
    } finally {
      setLoading(false);
    }
  }

  if (registered) {
    return (
      <AuthLayout title="Check your email">
        <p style={{ fontSize: "14px", color: "var(--color-text-muted)", lineHeight: 1.6, marginBottom: "20px" }}>
          We sent a 6-digit verification code to <strong style={{ color: "var(--color-text)" }}>{email}</strong>.
          Enter it on the next page to finish setting up your account.
        </p>
        <button
          style={primaryBtnStyle}
          onClick={() => router.push(`/verify-email?email=${encodeURIComponent(email)}`)}
        >
          Enter verification code
        </button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Create your account">
      <form onSubmit={handleSubmit} onFocusCapture={handleFormFocus} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        <div>
          <label htmlFor="fullName" style={labelStyle}>Full name</label>
          <input
            id="fullName" type="text" autoComplete="name" required
            value={fullName} onChange={(e) => setFullName(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label htmlFor="company" style={labelStyle}>Company name</label>
          <input
            id="company" type="text" autoComplete="organization" required
            value={company} onChange={(e) => setCompany(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label htmlFor="email" style={labelStyle}>Work email</label>
          <input
            id="email" type="email" autoComplete="email" required
            value={email} onChange={(e) => setEmail(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label htmlFor="password" style={labelStyle}>Password</label>
          <input
            id="password" type="password" autoComplete="new-password" required
            minLength={8}
            maxLength={128}
            value={password} onChange={(e) => setPassword(e.target.value)}
            style={inputStyle}
          />
          {password.length > 0 && (
            <div style={{ marginTop: "8px" }}>
              <div style={{ display: "flex", gap: "4px" }}>
                {[1, 2, 3, 4].map((seg) => (
                  <div
                    key={seg}
                    style={{
                      height: "3px",
                      flex: 1,
                      background: "var(--color-text)",
                      opacity: seg <= strength ? 1 : 0.15,
                    }}
                  />
                ))}
              </div>
              <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "4px", marginBottom: 0 }}>
                {passwordStrengthLabel[strength]}
              </p>
            </div>
          )}
        </div>
        <div>
          <label htmlFor="pilotCode" style={labelStyle}>Code (Optional)</label>
          <input
            id="pilotCode" type="text" autoComplete="off"
            value={pilotCode} onChange={(e) => setPilotCode(e.target.value)}
            onBlur={() => { void checkCode(pilotCode); }}
            style={inputStyle}
          />
          {codeCheck && codeCheck.code === pilotCode.trim() && (
            <p style={{ fontSize: "12px", color: codeCheck.valid ? "var(--color-text-muted)" : "#E53E3E", margin: "4px 0 0" }}>
              {!codeCheck.valid
                ? "This code is not valid."
                : codeCheck.kind === "referral"
                  ? "Code accepted. You get one month free on your second bill."
                  : "Code accepted."}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="signupSource" style={labelStyle}>How did you hear about us? (Optional)</label>
          <select
            id="signupSource"
            value={signupSource}
            onChange={(e) => setSignupSource(e.target.value)}
            style={inputStyle}
          >
            <option value="">Select one</option>
            {SIGNUP_SOURCE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {signupSource === "other" && (
            <input
              id="signupSourceDetail" type="text" autoComplete="off" maxLength={200}
              placeholder="Tell us more (optional)"
              value={signupSourceDetail} onChange={(e) => setSignupSourceDetail(e.target.value)}
              style={{ ...inputStyle, marginTop: "8px" }}
            />
          )}
        </div>

        <Turnstile onToken={setCaptchaToken} />

        <label style={{ display: "flex", alignItems: "flex-start", gap: "8px", fontSize: "13px", color: "var(--color-text-muted)", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={tosAccepted}
            onChange={(e) => setTosAccepted(e.target.checked)}
            style={{ marginTop: "2px" }}
          />
          <span>
            I agree to the{" "}
            <a href={`${SITE_URL}/legal/terms`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--color-text)" }}>Terms of Service</a>
            {" "}and{" "}
            <a href={`${SITE_URL}/legal/privacy`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--color-text)" }}>Privacy Policy</a>
          </span>
        </label>

        {error && (
          <p style={{ fontSize: "13px", color: "#E53E3E", margin: 0 }}>{error}</p>
        )}

        <button type="submit" style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1 }} disabled={loading}>
          {loading ? "Creating account…" : "Create account"}
        </button>
      </form>

      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginTop: "20px", textAlign: "center" }}>
        Already have an account?{" "}
        <Link href="/login" style={{ color: "var(--color-text)" }}>
          Sign in
        </Link>
      </p>
    </AuthLayout>
  );
}

export default function RegisterPage() {
  return (
    <Suspense>
      <RegisterForm />
    </Suspense>
  );
}
