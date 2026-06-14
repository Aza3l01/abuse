# Clew — MVP Roadmap

**Product:** Clew | **Website:** www.clewsec.com

Work through phases in order. Items within a phase can be parallelised where dependencies allow.

---

## Phase 1 — Correctness (before any real customer connects)

These are issues in the current codebase that cause incorrect results at scale. None are user-visible during development but each one breaks the product for real traffic.

### 1. Fix: per-IP batching (replaces fixed 500-record model)

The current `normalizer.py` splits all log lines into fixed 500-record chunks regardless of which IP they belong to. An attacker who sent 300 requests in a 15-minute window could be split across two batches and never be the dominant IP in either — their signal gets diluted or lost entirely.

**The correct production model:**
- Read all new log lines from S3 for the 15-minute window (same as now)
- Group records by source IP within that window
- For each IP with ≥ 10 requests: call `run_pipeline()` with only that IP's records
- Produces one verdict per IP per poll cycle (not one verdict per 500 lines)
- IPs with fewer than 10 requests are still counted in `ip_memory` (total_requests, last_seen) but do not trigger the full detection pipeline — not enough signal to be meaningful

**What to change:**
- `engine/source/ingestion/normalizer.py`: replace the fixed-batch split with group-by-IP. Return type changes from `list[list[dict]]` to `dict[str, list[dict]]` (IP → records)
- `workers/tasks/process_logs.py`: update the loop to iterate `ip_groups.items()`, call `run_pipeline(records_for_ip, ...)` per IP
- `engine/source/pipeline/run.py`: `primary_ip` derivation becomes `records[0]["ip"]` since all records share one IP

**Minimum threshold:** 10 requests per IP per window. Document in `CONTEXT.md` as a known tunable parameter — future Pro custom thresholds will expose this per-org.

**Known limitation to document in `CONTEXT.md`:** coordinated multi-IP attacks (botnets where thousands of IPs each send 1–2 requests) are not detected by per-IP analysis. Each IP stays below the threshold individually. This is a Pro-tier roadmap item requiring a cross-IP clustering pass over the full window.

---

### 2. Fix: per-org distributed lock on process_logs

If Celery Beat fires for an org while the previous `process_logs` task for that org is still running (large backlog on first connection), two workers will process the same S3 objects concurrently and produce duplicate verdicts.

```python
lock_key = f"clew:lock:process:{org_id}"
acquired = redis.set(lock_key, 1, ex=1200, nx=True)  # 20-min TTL, atomic
if not acquired:
    return {"status": "skipped", "reason": "already_running"}
```

Release in a `finally` block. The `nx=True` flag makes the acquire atomic — no race condition possible.

---

### 3. Fix: source_key deduplication on verdicts

If the distributed lock fails (Redis restart), the same S3 file gets processed twice. Defence-in-depth requires deduplication at the verdict level.

- Add `source_key` (string, nullable) column to `verdicts` — stores the S3 object key that produced the verdict
- Add unique index on `(org_id, source_key)` in the Alembic migration
- Before inserting: check if `(org_id, source_key)` already exists; if so, skip the insert
- Makes the pipeline effectively exactly-once for verdicts even if the same file is processed twice

---

### 4. Fix: 7-day historical window on first S3 connection

When `last_processed_key` is null (first connection), the current code reads all objects in the bucket. A client with 2 years of API Gateway logs has potentially millions of lines — causes memory pressure on t3.small and could take hours.

**Decision:** on first connection, list only S3 objects with `LastModified >= now() - 7 days`. After processing, set `last_processed_key` to the last object in that window and poll normally from there.

**Client-facing:** surface in onboarding wizard Step D: "On first connection, we'll process your last 7 days of logs. Older history is available on request."

**Document in `CONTEXT.md`:** the full `last_processed_key` logic — S3 lexicographic key ordering, at-least-once delivery model, how `source_key` deduplication (item 3) makes it exactly-once for verdicts, and what happens if the worker crashes mid-batch (last file reprocessed on next cycle, deduplication prevents double-verdicts).

**Future:** "Backfill" button (Pro tier) to ingest history older than 7 days on demand.

---

### 5. Fix: log format auto-detection on first poll

If the client selects API Gateway but their bucket contains ALB logs, the normalizer silently drops all lines. They get no verdicts, no error, and assume the product is broken.

On first poll (`last_processed_key` is null):
1. Fetch the first 10 lines of the most recent S3 object
2. Attempt to parse with the configured format
3. If parse success rate < 50%: try the other format
4. If the other format parses cleanly: abort ingestion, set `s3_status = "error"`, `s3_status_message = "Log format mismatch: logs appear to be ALB format but you selected API Gateway. Update your log format in Settings."`
5. Do not write any verdicts from a mismatched batch

---

### 6. Fix: login brute force protection

Item 38 rate-limits `/auth/register` but nothing protects `/auth/login`. A credential stuffing attack against Clew's own login endpoint is a real risk for a security product.

- Redis counter per email: `clew:login_fail:{sha256(email)}` — increment on every failed login attempt, expire after 15 minutes
- After 5 failed attempts within 15 minutes: return 429, lock that email from login for 15 minutes
- On lockout: send email from `noreply@clewsec.com` — "Someone is attempting to log in to your Clew account. Your account has been temporarily locked for 15 minutes."
- Successful login resets the counter
- Apply the same counter to `POST /auth/login/mfa` (TOTP brute force)
- Implement in the existing `api/routes/auth.py` login handler alongside the current slowapi rate limiter

---

### 7. Fix: CORS production origins

`api/main.py` already has CORS middleware. Verify before launch:

```python
allow_origins=[
    "https://www.clewsec.com",
    "https://clewsec.com",
]
```

Never `allow_origins=["*"]` on session-cookie-authenticated routes. Public API routes (`api.clewsec.com/v1/`) use API key auth (no browser cookies) so CORS is less critical there — but still tighten once the SDK client list is known.

---

### 7a. Fix: session invalidation on password change

Item 14 covers session expiry during normal use but nothing explicitly invalidates other sessions when the password changes.

- On `POST /auth/change-password` (settings) and `POST /auth/reset-password` (email reset): after updating `password_hash`, call `DELETE /auth/sessions` for all sessions except the current one
- Implementation: query `refresh_tokens` for all non-revoked tokens belonging to this client, set `revoked = True` on all except the token used in the current request
- Add a note in the success response / email: "For security, all other sessions have been signed out."
- This is a 3-line addition to the existing password update handlers

---

## Phase 2 — Organisation & Multi-user

### 7. Organisation / multi-user refactor

- Add `organizations` table — holds company name, S3 config, WAF config, Stripe/Razorpay billing, tier, alert_email
- Add `organization_members` table — links `Client` (login) to `Organization` with role: `owner | admin | viewer`
- Move off `Client`: s3_bucket, s3_prefix, log_format, aws_region, waf_ip_set_id, cloudflare_*, alert_email, tier, stripe_*, tier_expires_at, last_processed_key
- Also add to `organizations`: `last_scan_completed_at`, `last_scan_status`, `last_scan_error`, `s3_status`, `s3_status_message`, `s3_connected_at`, `billing_provider`, `pilot_tier`, `payment_method_display`, `monthly_requests_processed`, `monthly_requests_reset_at`, `blocking_tos_accepted_at`, `gstin`
- Rekey all FK columns: `Verdict.client_id` → `org_id`, `IpMemory.client_id` → `org_id`, `AlertSent.client_id` → `org_id`
- Update `api/deps.py` — add `get_current_org()` resolved from JWT → client → membership
- Update all route query filters (verdicts, dashboard, ips, clients, billing) to use `org_id`
- Update workers (process_logs, send_alerts, push_blocks) to use `org_id`
- Update engine normalizer `client_id` param → `org_id`
- Add `domain` field to `organizations` — extracted from owner's email at registration, editable by owner later
- Registration creates `Client` + `Organization` + `OrganizationMember(role=owner)` atomically
- Write Alembic migration — clean drop+recreate (no data to migrate yet)
- Write member invite flow: `POST /org/invite { email, role }` → emails a personalised one-time tokenized link → invitee clicks → `OrganizationMember` row created — directed invites only, no shareable public links
- Invite permission rules server-side: `owner` may invite `admin` or `viewer`; `admin` may only invite `viewer`; `viewer` cannot invite anyone
- **Domain-based role ceiling (enforced in API, not just UI):** if `invited_email` domain ≠ `org.domain` → role forced to `viewer`; API returns 400 if owner tries to invite external email as `admin`
- Add `org_invites` table: `id`, `org_id`, `invited_email`, `role`, `token_hash`, `expires_at`, `accepted_at` — single-use token, expires 7 days
- Invite acceptance: no account → `/accept-invite?token=...` → email pre-filled, set password, create `Client` + `OrganizationMember`, straight to dashboard (no wizard)
- Invite acceptance: existing account → link creates `OrganizationMember` row → redirect to dashboard or org switcher
- Any logged-in user can create an additional org ("+ New organisation" button) → short wizard → new `Organization` + `OrganizationMember(role=owner)` → org switcher shows both
- JWT payload carries `org_id` as well as `client_id`; single org → auto-select; multiple orgs → org switcher
- Add `GET /auth/orgs`, `POST /auth/switch-org`, `GET /auth/sessions`, `POST /auth/add-session`, `DELETE /auth/sessions/{session_id}`

**Unified account + org switcher (navbar dropdown):**

```
● kiran@gmail.com
    └ Razorpay       (viewer)   ← currently active
    └ PhonePe        (viewer)
  kiran@kirantech.com
    └ Kiran Tech     (owner)
──────────────────────
  + Add account
  Sign out
```

- Clicking an org under the current email → `POST /auth/switch-org`, new JWT
- Clicking an org under a different email → switches active session + org in one action
- Sessions stored server-side in Redis; `sessions` cookie lists active session IDs
- After login: single org → straight to `/dashboard`; multiple orgs → check `last_org_id` → if valid, straight to `/dashboard`; else `/select-org`

**Role enforcement:**
- `owner` / `admin`: full dashboard, settings, verdicts, IPs, block/unblock, team management
- `admin` restriction: no billing tab, cannot delete org
- `viewer`: read-only dashboard, verdicts, IPs; settings tab hidden; block/unblock hidden; team management hidden

---

### 8. Role-based access control (RBAC)

- `owner` — full access, billing, invite/remove members, delete org
- `admin` — full access except billing and org deletion
- `viewer` — read-only: dashboard, verdicts, IPs; cannot change config or trigger blocks
- Enforce in `get_current_org()` via role checks on each route
- Expose role in `/auth/me` response
- Settings > Team Members: owner can change roles / remove members; role promotion to `admin` only if member's email domain matches `org.domain`

---

### 9. Invite email content + acceptance page

**Subject:** `[Owner Name] invited you to join [Company Name] on Clew`
**From:** `team@clewsec.com` — monitored inbox

**Body:**
```
[Owner Name] has invited you to join [Company Name]'s security dashboard
on Clew as a [Viewer / Admin].

[Accept Invitation →]

This invitation expires in 7 days.

If you don't recognise this invitation, ignore this email — no account
will be created.
```

For existing Clew accounts: add "You already have a Clew account with this email. Clicking accept will add [Company Name] to your organisations."

**Acceptance page (`/accept-invite?token=...`):**
- Valid token, no account: email pre-filled (read-only), password field only, "Set password and accept" button. No OTP — the invite token is sufficient proof. After submit: create `Client` + `OrganizationMember`, redirect to dashboard.
- Valid token, existing account: "Accept invitation to [Company Name] as [Role]?" — Accept / Decline. After accept: redirect to dashboard.
- Expired token: "This invitation has expired. Ask [Owner Name] to resend it." + "Go to login →"
- Already-used token: "This invitation has already been accepted." + "Go to login →"

**Role selection in invite UI (enforced server-side regardless):**
- Owner + same-domain invitee: dropdown shows Admin / Viewer
- Owner + external email: no dropdown — fixed "Viewer (external collaborators are always viewers)" label
- Admin inviting: Viewer only, no dropdown

**Resend:** Settings > Team Members shows pending invites with "Resend" and "Cancel". Resend invalidates old token, generates new one, sends new email. Rate limit: once per hour per email address.

---

## Phase 3 — Registration & First-time Experience

### 10. Registration flow redesign — wizard + onboarding

**Step 1 — Registration page (minimal)**
- Email
- Password (with strength indicator)
- Cloudflare Turnstile CAPTCHA (see Phase 9 security hardening) — fires on submit
- ToS + Privacy Policy checkbox (required)
- Submit → create unverified account → send OTP email

**Note — invite-based registration is a separate path:** users arriving via `/accept-invite?token=...` do NOT go through this page. They land on a minimal "set your password" page (email pre-filled, no wizard, no org creation). After setting password they go straight to the org dashboard. See item 9.

**Step 2 — Email OTP verification**
- 6-digit OTP via SES; user enters it on `/verify`
- OTP expires 15 minutes; resend link available after 60 seconds
- On success → `email_verified=True`, `tos_accepted_at` timestamp → redirect to dashboard

**Step 3 — MFA nudge (dashboard, not blocking)**
- On first dashboard load after verification: dismissible banner/modal nudging MFA setup
- "Secure your account — enable two-factor authentication" with link to `/dashboard/settings#mfa`
- Do NOT force MFA. Track `mfa_nudge_dismissed_at` so it does not repeat.

**Step 4 — Company profile wizard (post-verification popup)**
Multi-step modal, progress indicator, skippable:

*Page 1 — About you and your company:*
- Full name, job title (dropdown: Founder / CTO / VP Engineering / Security Engineer / DevOps / Other)
- Company name, company size (1–10 / 11–50 / 51–200 / 201–500 / 500+)
- Industry (Fintech / SaaS / E-commerce / Healthtech / Edtech / Other)
- Primary use case (API abuse detection / Bot blocking / Credential stuffing protection / DDoS mitigation / All of the above)
- How did you hear about Clew — optional (Google / LinkedIn / Twitter/X / Word of mouth / GitHub / Other)

*Page 2 — Your AWS setup:*
- AWS region (dropdown, ap-south-1 defaulted for India)
- Log source (radio: API Gateway / ALB / Both / Not sure yet)
- Do you use Cloudflare? (yes/no)
- Do you use AWS WAF? (yes/no)
- Pre-populate settings page fields from these answers

**Step 5 — Optional setup walkthrough (page 3 of modal)**
"Want a quick walkthrough of connecting your first S3 bucket?" — Yes / Skip

If Yes:
- Step A: Enable API Gateway access logs → S3 (AWS console instructions)
- Step B: Create IAM user with required policy (exact JSON to copy)
- Step C: Paste credentials into `/dashboard/settings#s3`
- Step D: "On first connection, we'll process your last 7 days of logs. Your first results appear within 15 minutes."

**Data storage on registration:**
1. `Client` — email, password_hash, full_name, job_title, tos_accepted_at, email_verified=False
2. `Organization` — company_name, tier="starter", trial_ends_at=now()+30d, billing_provider=null, all config fields null
3. `OrganizationMember` — client_id, org_id, role="owner"

Wizard page 1 updates `Organization`: company_size, industry, use_case, how_did_you_hear
Wizard page 2 updates `Organization`: aws_region, log_format, has_cloudflare, waf_ip_set_id placeholder
Wizard completion updates `Client`: wizard_completed_at

---

### 11. Trial billing — no card required, 30-day default for all customers

Every new org starts with:
- `tier = "starter"`, `trial_ends_at = now() + 30 days`, `billing_provider = null`
- No Stripe, no Razorpay, no card required at any point during signup

**Dashboard trial banner** (non-dismissible until payment added):
> "30-day trial — 22 days remaining. [Add payment method →]"

**Communication schedule (Beat tasks):**
- Day 25: email from `billing@clewsec.com` — "Your Clew trial ends in 5 days."
- Day 28: email — "2 days left on your Clew trial."
- Day 30, no payment: revert org to limited state

**On trial expiry:**
- Never lock the client out — they can still log in and see existing verdicts (data retained)
- Stop new scans: Beat skips orgs with `trial_ends_at < now()` and `billing_provider = null`
- Dashboard shows persistent top banner: "Your 30-day trial has ended. Add a payment method to continue with Starter."
- CTA button → Razorpay (INR) or Stripe (USD) checkout

**INR pilot promo code path:**
- Client enters promo code → "Start 30-day pilot" button appears
- Backend: validate code → set `tier`, `trial_ends_at = now() + 30d`, `billing_provider = "pilot"`, `pilot_code_used = code`
- No Razorpay subscription created
- Promo code row marked redeemed
- Day 25/28/30 emails still fire
- Day 30 no payment: revert tier, banner, Razorpay checkout on "Add payment method" click
- After successful payment: create subscription, `billing_provider = "razorpay"`, clear pilot state

**Columns needed on `organizations`:** `billing_provider` (stripe / razorpay / pilot / null), `pilot_tier`, `payment_method_display`, `pilot_code_used`

---

### 12. Terms of Service, Privacy Policy, and DPA

- Create `/terms` page — placeholder initially; real content required before any paying customer connects S3
- Create `/privacy` page — same
- Add links to both in the Footer component
- Add checkbox to registration: "I agree to the Terms of Service and Privacy Policy" (required, validated on submit)
- Store `tos_accepted_at` timestamp on `Client` at registration
- ToS must include: "You may request deletion of your account at any time from your account settings. Your data will be permanently deleted within 30 days of your request." (required for DPDP compliance — see item 40)

**DPA (Data Processing Agreement):**
Clew ingests customer API log data. Any fintech or healthtech CTO will ask for a DPA before connecting S3 — it is standard for B2B SaaS that touches production data. A DPA is not complex at this stage: it covers what data is processed, how long it is retained, what subprocessors are used (AWS SES, MaxMind, Groq for Pro), and deletion rights. Have it ready as a PDF to send on request. It does not need to be self-serve at MVP — a `mailto:legal@clewsec.com` link on the `/terms` page is sufficient. The CA drafting the Subscription Agreement should draft this simultaneously.

---

### 13. MFA recovery codes — display + login recovery path

The `mfa_backup_codes` table with 10 hashed single-use codes already exists. The UI is missing.

**During MFA setup** (after `POST /auth/mfa/verify` returns success):
- Response includes 10 plaintext codes — shown exactly once, never stored in plaintext
- Display: monospace grid (Geist Mono), all 10 codes visible
- Warning: "Save these somewhere safe — if you lose access to your authenticator app, these are the only way to recover your account. They cannot be shown again."
- "Copy all codes" button (copies newline-separated to clipboard)
- "I have saved these codes" checkbox — must be checked before "Done" button becomes active

**MFA login challenge page:**
- Below the TOTP input: "Use a recovery code instead" link
- Clicking replaces TOTP input with a single recovery code field
- On submit: verify against hashed values in `mfa_backup_codes`, mark the row consumed, log in
- If all 10 codes are exhausted: "All recovery codes have been used. Disable and re-enable MFA from your security settings to generate new codes." — prevent recovery path login (TOTP still works)

---

### 14. Session expiry — silent refresh + expired-session modal

On any 401 response from the API:
1. Frontend intercepts in `lib/api.ts` (the central API client)
2. Attempts silent refresh via `POST /auth/refresh`
3. If refresh succeeds: retry the original request transparently — user notices nothing
4. If refresh fails: show an inline modal overlay (not a full-page redirect):
   > "Your session has expired. Please log in again."
5. Single "Log in" button → `/login?next=[encodeURIComponent(window.location.pathname + window.location.search)]`
6. After login: middleware reads `next` param and redirects back

Do not use `window.location.href` redirect from within an API call — this destroys unsaved form state.

---

## Phase 4 — Dashboard Completeness

### 15. Dashboard empty states + scanning-in-progress state

**S3 not configured** (all sections):
- Dashed-border box (1px dashed `--color-border`) with centered text
- "Connect your S3 bucket to start monitoring"
- CTA button "Connect S3 → Settings" deep-linking to `/dashboard/settings#s3`
- Summary stat cards show `—`

**S3 configured, no verdicts yet:**

| Component | Empty state text | CTA |
|---|---|---|
| Summary stat cards | `0` with muted subscript "No data yet" | None |
| Trend chart | Empty axes + "No threats detected yet. Your first scan runs within 15 minutes." | None |
| Top IPs table | "No IPs flagged yet" — full-width muted table row | None |
| Verdicts list | "No threats detected yet — your first scan runs within 15 minutes of connecting S3." | "Check Settings →" |

**Scanning in progress (S3 just saved, no verdicts yet):**
- Persistent non-dismissible top banner: "Scanning in progress — your first results will appear here within 15 minutes."
- Dismissed automatically when first verdict arrives

**Auto-polling window:**
- Frontend polls `GET /dashboard/summary` every 30 seconds for the first 30 minutes after `s3_connected_at`
- When response transitions from zero verdicts to any verdicts: refresh full page data, dismiss banner
- After 30 minutes or first data: polling stops; replace with manual "Refresh" button showing last-checked time
- Never poll indefinitely

**Add to `organizations`:** `s3_connected_at` (timestamp — set when S3 config is first saved successfully)

---

### 16. S3 / WAF / Cloudflare connection health indicators + error messages

**S3 status badge** (Settings S3 section, below Save button):
- `Connected` — green border, "Connected — last ingested [time]"
- `Not tested` — muted, "Not tested — click Save to test"
- `Error: [reason]` — red border, specific message

**S3 error codes → user-facing messages:**

| Code | Message |
|---|---|
| `s3_invalid_access_key` | "Invalid Access Key ID — verify AWS_ACCESS_KEY_ID in your IAM console" |
| `s3_invalid_secret_key` | "Invalid secret access key — verify the key pair matches in your IAM console" |
| `s3_bucket_not_found` | "Bucket '{name}' not found in region '{region}' — check the bucket name and AWS region" |
| `s3_access_denied` | "Access denied to s3://{bucket}. Missing permission: `s3:GetObject`. Add this to your IAM policy: [copyable JSON snippet]" |

The IAM permissions error must show the exact missing permission from the AWS error response — this is the most common failure case and must be self-service fixable.

Test connection on save — the save itself triggers the connection test. Confirmation only appears after the test passes.

**Dashboard header S3 indicator:** compact dot badge — `S3 active` (green) or `S3 error` (red), links to `/dashboard/settings#s3`.

**Add to `organizations`:** `s3_status` (connected / error / null), `s3_status_message` (string)

---

### 17. Worker health & last-scanned timestamp

The last-scanned timestamp is the primary trust signal in the product. It proves Clew is running. Lives in the dashboard header, always visible.

**Add to `organizations`:** `last_scan_completed_at` (timestamp), `last_scan_status` (success / error / in_progress), `last_scan_error` (string)

**Update `process_logs.py`:**
- Set `last_scan_status = "in_progress"` at task start
- Set `last_scan_status = "success"`, `last_scan_completed_at = now()` at task end
- Set `last_scan_status = "error"`, `last_scan_error = str(exc)` on exception

**Dashboard display logic:**

| State | Display |
|---|---|
| `last_scan_completed_at` < 20 min ago | "Last scanned: X minutes ago" in muted text |
| 20–60 min ago | Same text in amber (`--color-medium`) |
| > 60 min ago | "Scan overdue — last completed X ago" in orange (`--color-high`) |
| `last_scan_status = "error"` | "Last scan failed — check settings" in red, links to settings |
| `last_scan_completed_at` null | "Scan pending..." |

Add these fields to `GET /dashboard/summary` response.

---

### 18. Verdict list — pagination, columns, filters

**Pagination:** 25 rows per page. Footer: page size selector (10 / 25 / 50) + Previous / 1 2 3 … / Next controls.

**Default sort:** severity descending (Critical first), then timestamp descending within each band.

**Columns:**

| Column | Format |
|---|---|
| Timestamp | Relative ("2 hours ago"), absolute on hover tooltip |
| IP | Geist Mono, copyable on click |
| Attack Type | Human-readable label ("Credential Stuffing", "DDoS") — not internal code |
| Severity | Square badge using functional colors |
| Confidence | Percentage ("87%") in muted text |
| Blocked | "Blocked" badge (green) or `—` |
| Actions | "View" button → detail page |

**Filters (above table, collapsible):**
- Severity: multi-select checkboxes — Critical / High / Medium / Low. Default: all.
- Date range: preset buttons (Last 24h / 7d / 30d / 90d) + custom date picker. Default: 30d.
- IP: text input, exact or prefix match (e.g. `192.168.` finds a subnet).
- Attack type: dropdown, populated from distinct `threat_type` values in verdicts table.

**IP filter via query param:** clicking an IP in the Top IPs table navigates to the verdicts list with IP pre-applied: `/dashboard/alerts?ip=1.2.3.4`

**Top IPs table columns:**

| Column | Notes |
|---|---|
| IP | Geist Mono |
| Total Requests | Number, right-aligned |
| Last Seen | Relative time |
| Highest Severity | Badge |
| Country | Flag emoji + ISO code from GeoLite2-City |
| ASN | Provider name from GeoLite2-ASN ("DigitalOcean", "AWS") |
| Blocked | Badge or `—` |
| Actions | "View verdicts →" → `/dashboard/alerts?ip=[ip]` |

---

### 19. Verdict detail page — complete spec

Route: `/dashboard/verdicts/[id]`

**Field list:**

| Field | Notes |
|---|---|
| IP | Large, copyable, Geist Mono |
| Country + ASN | "India · DigitalOcean AS14061" from GeoLite2 |
| Attack type | Human-readable (not internal code) |
| Severity badge + confidence % | Side by side |
| First seen / Last seen | From `ip_memory` |
| Total requests | From `ip_memory` |
| Timestamp | When this verdict was generated |
| Agent scores | 7-row table: agent name, score (0–1), Triggered column (row bolded if triggered) |
| Raw log sample | 5 most anomalous request lines (see below) |
| AI Analysis | Pro only: Groq explanation. Non-Pro: lock icon + "Upgrade to Pro to unlock AI-generated threat analysis." Never blank. |
| Block this IP | Button — Growth+ tier, owner/admin role only |
| View all verdicts for this IP | Link → `/dashboard/alerts?ip=[ip]` |

**Raw log sample:** the 5 most suspicious individual request lines from the batch, selected by per-record suspicion scores from the detection agents. Displayed in a `<pre>` block (Geist Mono) with caption "5 most suspicious requests from this batch." Store as `verdicts.sample_logs` (JSON array, max 5 entries, each raw log line truncated at 512 chars).

**Agent scores display:** table with columns Agent, Score, Triggered. Bold rows where triggered=true. No bar chart — a table fits the design language.

---

### 20. Alerts page — test alert + delivery status

Existing spec (list of alert emails sent with timestamp + triggering verdict) plus:

**"Send test alert" button** — at the top of the page, owner/admin only:
- Calls `POST /alerts/test`
- Generates a dummy verdict (not persisted) and sends it through the full SES path to the configured `alert_email`
- Button shows "Sending..." during the request, then inline success/failure feedback
- Clients will click this immediately after saving their alert email

**Alert email display:** show as read-only context above the table: "Sending alerts to: alerts@yourcompany.com" — link "Change in Settings →". Do not duplicate the email input on this page.

**Delivery status column:** add `delivery_status` (sent / failed / bounced) and `delivery_error` (string) to `alerts_sent`. For MVP, `sent` is sufficient — add SES bounce/complaint handling via SNS as a fast-follow.

---

### 21. Blocked IPs page — partial block state, unblock confirmation, manual block

**Partial block state:**
Add to `ip_memory`: `waf_blocked` (bool), `cloudflare_blocked` (bool), `waf_block_error` (string), `cloudflare_block_error` (string).

`push_blocks.py` updates each independently. WAF success + CF failure → `waf_blocked=True`, `cloudflare_blocked=False`.

Display as dual inline badges per row:
- `WAF ✓` (green) / `WAF ✗` (red, error tooltip on hover)
- `CF ✓` (green) / `CF ✗` (red, error tooltip on hover)

**Unblock confirmation modal:**
> "Unblock [IP address]?
> This IP was blocked for [attack type] on [date]. It will be removed from your WAF and Cloudflare rules immediately. This action is logged."

Buttons: "Cancel" / "Confirm Unblock" (primary).

**On subscription downgrade below Growth:**
Do NOT automatically remove existing WAF/Cloudflare rules — removing active blocks on downgrade is a security incident. Show persistent banner:
> "Your subscription no longer includes automatic blocking. Existing blocked IPs remain active in your WAF and Cloudflare. New threats will not be blocked until you upgrade to Growth."

**Manual block without a verdict:**
"Block an IP manually" button (owner/admin only). Form: IP address input + optional reason text. Creates a verdict row with `threat_type = "manual"`, `confidence = 1.0`, `severity = "high"`, then triggers the normal block flow. Appears in both the verdicts list (labeled "Manual block") and the blocked IPs page.

---

### 22. Settings page — section map + save behaviour

**Ordered sections** (full-width `border-top: 1px solid var(--color-border)` between each):

1. **S3 Configuration** — bucket name, prefix, AWS region, log format radio (API Gateway / ALB), access key ID, secret key (masked), "Save & Test Connection" button, status badge
2. **WAF Configuration** — IP set ARN, "Test WAF Connection" button, status badge. Visible only if tier ≥ Growth.
3. **Cloudflare Configuration** — API token (masked), zone ID, "Test Cloudflare Connection" button, status badge. Visible only if tier ≥ Growth.
4. **Alert Email** — email address, severity threshold (All threats / High + Critical only), "Send test alert" link
5. **Webhook Alerts** — webhook URL, Slack auto-detect, per-channel toggles. Growth+ only.
6. **Team Members** — invite form (email + role), member list with role badges, pending invites with "Resend" / "Cancel"
7. **API Keys** — create named keys, set expiry, copy once, revoke
8. **Billing** — current tier, status, payment method display, next invoice date, upgrade/downgrade/cancel
9. **Security** — MFA setup/disable, change password (requires current password), active sessions list with per-session revoke, account deletion link (bottom, styled critical)

**Save behaviour:**
- Each section has its own Save button — no autosave
- After save: inline "Saved ✓" for 3 seconds (no toast — inline fits the design language)
- S3 save triggers an immediate connection test; confirmation only shows after the test passes
- On successful S3 save: immediately enqueue `process_logs` task for this org. Show: "Settings saved — queuing first scan..."

---

### 23. WAF / Cloudflare credential validation test buttons

Same test-and-show-result pattern as S3 save-and-test.

**WAF test (`POST /settings/test-waf`):**
- Calls `wafv2:GetIPSet` with the provided ARN
- Success: "Connected — IP set contains X IPs"
- Failure: specific AWS error (invalid ARN, permission denied, region mismatch)

**Cloudflare test (`POST /settings/test-cloudflare`):**
- Calls `GET https://api.cloudflare.com/client/v4/zones/{zone_id}` with the provided token
- Success: "Connected — Zone: yourdomain.com"
- Failure: Cloudflare error code (invalid token, zone not found, insufficient permissions)

Both tests also fire on the Save button press — not only on the standalone test button.

---

## Phase 5 — Email & Communications

### 24. HTML email templates

All emails are currently plain text (`api/auth_utils.py`). Add HTML versions with the Clew wordmark, brand colours, clean layout.

**Templates needed:**
- Email verification OTP
- Password reset OTP
- MFA enabled confirmation
- Alert (high/critical verdict) — most important
- Welcome (post-verification)
- **Subscription confirmed (first payment only)** — fires after the *first* successful Razorpay/Stripe payment only, not on renewals. Content: "Payment confirmed. You're now on [Tier]." + one CTA button "Set up your S3 connection →" deep-linking to `/dashboard/settings#s3`. Renewals: let Razorpay/Stripe deliver the invoice directly — no additional Clew email needed, it's clutter for an existing customer.
- Failed payment (link to `/dashboard/settings`)
- Trial expiry warning (Day 25, Day 28, Day 30)
- Team invite (see item 9)

**Rules:**
- Keep plain-text fallback in all emails for spam filter compatibility
- Use inline CSS only — Gmail strips `<style>` blocks
- Python string templates with `{variable}` interpolation — no template engine needed at this scale

---

### 25. Email from-addresses

Configure four SES verified sending identities. All need SPF/DKIM/DMARC in Route 53.

| Email type | From | Reply-To |
|---|---|---|
| High/critical threat alerts | `alerts@clewsec.com` | `alerts@clewsec.com` (monitored) |
| Email OTP verification | `noreply@clewsec.com` | — |
| Password reset OTP | `noreply@clewsec.com` | — |
| MFA setup/disabled | `noreply@clewsec.com` | — |
| Welcome email | `hello@clewsec.com` | `hello@clewsec.com` |
| Trial expiry / billing reminders | `billing@clewsec.com` | `billing@clewsec.com` |
| Payment failure | `billing@clewsec.com` | `billing@clewsec.com` |
| Team invite | `team@clewsec.com` | `team@clewsec.com` |

Rationale: `alerts@` receives replies from CTOs at 2 AM asking "is this real?" — must go somewhere useful. `billing@` receives finance teams forwarding invoices. `noreply@` for transactional codes where replies make no sense.

**Email deliverability warmup:**
A cold domain sending batch alert emails lands in spam. Before launch:
1. Configure SPF, DKIM, DMARC in Route 53 for all four sending identities
2. Request SES production access (sandbox limits to 200 emails/day and verified-only recipients) — submit the production access request early, AWS takes 24–48 hours
3. Warmup sequence: send low volumes for the first 2 weeks (verification emails, welcomes only), then gradually include alerts. Do not send batch prospecting emails from the same domain — keep `clewsec.com` purely transactional
4. Monitor bounce rate in SES → if > 5%, pause and investigate before SES suspends the account

---

## Phase 6 — Billing

### 26. Promo code table — single-use, 100 codes

**Schema:**
```
promo_codes: id, code (unique e.g. CLEW-A3F9X), provider_coupon_id_stripe,
             provider_offer_id_razorpay, redeemed_at, redeemed_by_org_id
```

**Flow:**
- Generate 100 codes at launch via a one-time script
- Each code linked to a Stripe coupon (100% off, 1 month, single-use) and a Razorpay offer (equivalent)
- At checkout: validate `code` exists AND `redeemed_at IS NULL` → pass provider coupon/offer ID to checkout session → on successful payment webhook: mark `redeemed_at`, `redeemed_by_org_id`
- When all 100 used: return "This promo code is no longer available" — do not delete rows

**Why a custom table over 100 Stripe coupon objects:** analytics (when/by whom each code was used), bulk expiry without Stripe API calls, same code works for both Stripe (USD) and Razorpay (INR) clients.

Do not publish on the public pricing page — keep for direct outreach only.

---

### 27. INR pilot billing state — no card at signup

For INR customers (and early-access generally), no Razorpay subscription is created at signup. The promo code triggers a pilot state.

`billing_provider = "pilot"` path:
1. Client enters promo code → "Start 30-day pilot" button
2. Backend: validate code → set `tier`, `trial_ends_at = now() + 30d`, `billing_provider = "pilot"`, `pilot_code_used`
3. No Razorpay subscription created — none needed yet
4. Promo code row marked redeemed
5. Beat task sends Day 25 / Day 28 emails from `billing@clewsec.com`
6. Day 30, no payment: tier reverted, persistent dashboard banner
7. Client clicks "Add payment method" → Razorpay checkout for their tier
8. After successful Razorpay payment: create subscription, `billing_provider = "razorpay"`, clear `billing_provider = "pilot"` state

---

### 28. Growth upgrade — blocking TOS acceptance modal

Clients upgrading from Starter to Growth are now authorising active IP blocking in their WAF — materially different from passive monitoring.

At the moment "Upgrade to Growth" is clicked, before the payment flow opens:

> "Growth subscription includes active IP blocking
> Clew will automatically add malicious IPs to your AWS WAF and Cloudflare account.
> This is an active security action, not just monitoring.
> By continuing, you accept the [Growth Subscription Agreement ↗]."

Buttons: "Cancel" / "I understand — continue to payment"

- Store `blocking_tos_accepted_at` on `Organization`
- Backend checks this before processing any block action — returns 403 if not set
- One-time acceptance — subsequent billing changes (monthly → annual) do not re-trigger it

---

### 29. Complete payment integration — Stripe + Razorpay

Implement Razorpay (INR) before Stripe (USD) — INR customers are the first target market and Stripe requires company registration.

**Razorpay (INR customers — modal-based checkout):**
- Add `razorpay` to `requirements.txt`
- Frontend: load Razorpay Checkout via `<script src="https://checkout.razorpay.com/v1/checkout.js">` at runtime — always a browser script tag, cannot be bundled; add `declare global { interface Window { Razorpay: any } }` in `src/lib/razorpay.d.ts`
- Env vars: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`
- Plan IDs (created in Razorpay dashboard): `RAZORPAY_PLAN_STARTER_MONTHLY_INR`, `RAZORPAY_PLAN_STARTER_ANNUAL_INR`, `RAZORPAY_PLAN_GROWTH_MONTHLY_INR`, `RAZORPAY_PLAN_GROWTH_ANNUAL_INR`, `RAZORPAY_PLAN_PRO_MONTHLY_INR`, `RAZORPAY_PLAN_PRO_ANNUAL_INR`
- `POST /billing/razorpay/create-subscription` — create Razorpay Subscription, return `subscription_id` + `key_id`
- `POST /billing/razorpay/verify-payment` — verify HMAC-SHA256 of `razorpay_payment_id|razorpay_subscription_id`; on success update tier
- `POST /billing/razorpay/webhook` — HMAC-SHA256 via `X-Razorpay-Signature`; handle `subscription.activated`, `subscription.halted`, `subscription.cancelled`, `payment.failed`
- `POST /billing/razorpay/cancel` — cancel API, revert tier, confirmation modal
- GST: add `gstin` to `Organization`; pass to Razorpay order for GST-compliant PDF invoices
- UPI as default: `config: { display: { sequence: ["block.upi", "block.card", "block.netbanking", "block.wallet"] } }`
- DB migration: add `razorpay_customer_id`, `razorpay_subscription_id` to `Organization`

**Stripe (USD customers — redirect-based checkout):**
- Production keys pending company registration — implement after first clients
- Create monthly and annual Price objects for all 3 tiers (12 price IDs total)
- `allow_promotion_codes=True` in checkout session creation
- `payment_method_collection: 'if_required'` — USD customers can also start without a card
- Stripe Customer Portal handles cancellation, payment method update, invoice download
- Webhook already handles `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`

**Shared billing features:**
- Annual billing: 2 months free (~17%); pricing page Monthly / Annual toggle
- Payment method display: "UPI • azael@okhdfcbank" (Razorpay) / "Visa ···· 4242" (Stripe)
- Failed payment email: beyond provider auto-retry, immediate Clew-branded email from `billing@clewsec.com`
- Currency routing: India timezone → Razorpay (INR); all other → Stripe (USD); manual override available
- Extend `GET /billing/status` to include: `razorpay_subscription_id`, `payment_method_display`, `billing_period`, `trial_ends_at`

**Upgrade/downgrade proration decision (Razorpay):**
Razorpay subscriptions have no native plan-change endpoint — upgrade/downgrade = cancel current + create new subscription.
- **Upgrade (e.g. Starter → Growth):** new subscription starts immediately, old subscription cancelled. No refund or proration for unused days on the old plan. Billing modal copy: "Your [Growth] plan starts immediately. Unused days on your current plan are not refunded." They're gaining features, they accept this.
- **Downgrade (e.g. Growth → Starter):** current subscription runs to end of the current billing cycle, new subscription created to start from next cycle. Blocking features (WAF/CF) remain active until cycle end — do not remove them early. Billing modal copy: "Your plan changes to [Starter] on [date]. You'll keep [Growth] features until then."
- **Stripe:** uses `proration_behavior: 'none'` on subscription update — same decision, no proration. Consistent UX across both payment providers.

---

## Phase 7 — Usage Metering & Limits

### 30. Usage metering + monthly reset + soft quota limits

"API calls/month" means the client's own API traffic processed by Clew — total HTTP request lines ingested from their S3 logs per billing month. Not Clew's own API call counts.

**Add to `organizations`:** `monthly_requests_processed` (integer), `monthly_requests_reset_at` (date)

**Implementation:**
- `process_logs.py`: increment `monthly_requests_processed += len(records)` after each successful poll
- New Beat task `reset_monthly_counters`: runs on the 1st of each month at 00:00 UTC, zeroes counter, updates `monthly_requests_reset_at`
- Register in `workers/beat.py` Beat schedule alongside the existing `poll_all_clients` entry: `'reset-monthly-counters': {'task': 'workers.tasks.process_logs.reset_monthly_counters', 'schedule': crontab(hour=0, minute=0, day_of_month=1)}`

**Soft limits — never hard-cut a security tool:**

| State | Action |
|---|---|
| 80% of monthly limit | Dashboard amber banner: "You've used 80% of your monthly log quota. [Upgrade →]" + email |
| 100% reached | Dashboard persistent red banner: "Monthly quota reached — logs are still being processed to maintain protection. [Upgrade →]" + email |
| Over limit > 7 days | Same red banner + daily email reminder |
| Month resets | Counter zeroed, banners dismissed automatically |

Never stop scanning. Cutting off detection is worse than going over quota. The client needs to see the value of the extra volume before paying for it.

---

### 31. Usage / quota display in dashboard

Show in the billing card or dashboard summary: "X / 10M requests processed this month" with a progress bar. Turns amber at 80%, red at 100%.

---

## Phase 8 — Integrations & Product Features

### 32. GeoLite2-ASN database integration

`GeoLite2-City.mmdb` is in place and `scripts/download_geoip.sh` handles both files. The ASN database needs wiring into the product.

- Add `GEOIP_ASN_DB_PATH` env var pointing to `engine/datasets/GeoLite2-ASN.mmdb` — use env var so the path can be swapped without a code change
- Add `geo_asn_number` (integer) and `geo_asn_org` (string, e.g. "DigitalOcean LLC") to `ip_memory` — Alembic migration
- Populate via `geoip2.database.Reader` on `ip_memory` UPSERT in `process_logs.py`
- Handle `None` from the reader gracefully — graceful null for IPs not in the database
- Monthly update: `scripts/download_geoip.sh` handles both databases; add the monthly cron to the production server (see DEPLOY.md — already documented there)

---

### 33. Groq integration — explainable verdict summaries (Pro tier)

- The LLM client (`engine/source/llm/client.py`) already supports any OpenAI-compatible endpoint
- Add `GROQ_API_KEY` to `.env`
- Add Groq as the production LLM: `base_url="https://api.groq.com/openai/v1"`, `model="llama-3.3-70b-versatile"`
- In `engine/source/pipeline/run.py` — after verdict is produced, if `tier == "pro"`: call Groq to generate a 1–3 sentence human-readable explanation, stored in `verdicts.explanation`
- Gate `explanation` field in the verdicts API response behind tier check
- Verdict detail page: show explanation in an expandable card for Pro users; non-Pro users see the lock icon upsell (see item 19)
- Fall back to Ollama/local for dev (`DEBUG=1`) so no API key needed locally

---

### 34. Webhook / Slack / PagerDuty alert channels

- Add `alert_webhook_url` field on `Organization`
- Send JSON POST on high/critical verdicts (org-level toggle: all severities vs high+ only)
- Auto-detect Slack incoming webhook URL format → send formatted Slack Block Kit message
- PagerDuty Events API v2 integration (separate `pagerduty_routing_key` field)
- Per-channel on/off toggles in Settings > Webhook Alerts section
- `send_alerts.py` Celery task already exists — extend it
- Gating: email = starter+, webhook = growth+, PagerDuty = pro

---

### 35. Public customer-facing API + API keys

Customers will want to pull verdicts into their own SIEM, Splunk, Datadog, etc.

- Add `api_keys` table: `id`, `org_id`, `name`, `key_hash` (SHA-256), `scopes` (JSON list), `last_used_at`, `expires_at`, `revoked`
- Accept `Authorization: Bearer <key>` in addition to session cookies across all routes
- Scopes: `verdicts:read`, `ips:read`, `config:write`, `blocks:write`
- Settings > API Keys: create named keys, set expiry, copy once, revoke
- Public API base: `https://api.clewsec.com/v1/`
- Endpoints: `GET /v1/verdicts`, `GET /v1/verdicts/{id}`, `GET /v1/ips`, `POST /v1/ips/{ip}/block`, `POST /v1/ips/{ip}/unblock`, `GET /v1/org`, `PATCH /v1/org`

---

### 36. Rate limiting on public API endpoints

Apply `slowapi` to all `/v1/` routes, keyed by API key (not IP).

| Tier | Limit |
|---|---|
| Starter | 1,000 requests/hour |
| Growth | 10,000 requests/hour |
| Pro | 100,000 requests/hour |

Return on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

On 429: `{"error": "rate_limit_exceeded", "retry_after_seconds": N}`

Per-endpoint rate limiting and burst allowances are post-MVP.

---

### 37. In-product documentation / integration guide

- Create `/docs` route in Next.js (design matches existing design system)
- Sections: Quick Start, Enable API Gateway access logs → S3, Enable ALB access logs → S3, Required IAM permissions (policy snippet), Setting up WAF IP set blocking, Setting up Cloudflare IP blocking, Understanding verdicts and severity levels, Alert emails, Team members / inviting colleagues, FAQ
- Add "Docs" link to Navbar

---

## Phase 9 — Security & Compliance

### 38. Security hardening

- Add `Content-Security-Policy` header in Nginx config
- Add `Permissions-Policy` and `Referrer-Policy` headers
- Rate-limit `/auth/register` more aggressively (currently 5/hour — confirm on staging)
- **CAPTCHA: Cloudflare Turnstile** — free, privacy-respecting, invisible/managed modes. Add `TURNSTILE_SECRET_KEY` env var; verify server-side via `POST https://challenges.cloudflare.com/turnstile/v0/siteverify` in the register route before creating the account. Add widget to: registration page, forgot-password page.

---

### 39. Forgot password flow — complete spec

**Model:** 6-digit OTP (consistent with email verification — not a URL token).

**Redis key:** `SET clew:reset:{sha256(email)} {otp_hash} EX 900` (15-minute TTL). Each new reset request overwrites — only the latest code is ever valid. No DB table needed.

**Multiple requests:** Redis overwrite handles this automatically.

**Rate limiting:** max 3 reset requests per email per hour (Redis counter). Show: "Too many reset requests — please wait before requesting another code."

**After successful reset:** issue session cookies, redirect to `/dashboard` immediately. Do not show a "password reset successful" screen — the reset is proof of identity.

**Settings password change:** separate endpoint `POST /auth/change-password`. Requires `current_password` in addition to `new_password`. Different from the email-based reset — settings requires knowing the current password.

---

### 40. Account deletion — DPDP Act requirement

India's DPDP Act (referenced in the ToS) requires the ability to delete a client's data on request.

- "Delete account" link at the bottom of Settings > Security, styled `--color-critical`
- Modal: text confirmation input, must type "DELETE" exactly before the delete button activates
- `POST /auth/delete-account` — requires the text confirmation in the request body
- Soft-delete: set `deleted_at` on `Client`, anonymize email to `deleted-[uuid]@deleted.clew`, cancel active Stripe/Razorpay subscriptions via API
- Hard-delete after 30 days via scheduled Beat cleanup task
- ToS must reference: "Your data will be permanently deleted within 30 days of your deletion request."

---

## Phase 9b — Operations

### 47. Database backup strategy

Taking money from customers with no automated backup is a liability. PostgreSQL on a single EC2 instance with no backup = data loss risk on instance failure.

**MVP approach — nightly pg_dump to S3:**

```bash
# Add to crontab on the production server
0 2 * * * pg_dump postgresql://clew:PASSWORD@localhost/clew | gzip > /tmp/clew_$(date +\%Y\%m\%d).sql.gz && aws s3 cp /tmp/clew_$(date +\%Y\%m\%d).sql.gz s3://YOUR-BACKUP-BUCKET/db-backups/ && rm /tmp/clew_$(date +\%Y\%m\%d).sql.gz
```

- Create a dedicated S3 bucket `clew-db-backups` with a lifecycle rule deleting objects older than 30 days
- The `clew-server` IAM user already has S3 permissions — add `s3:PutObject` on the backup bucket specifically
- Test restore before first paying customer: `gunzip < backup.sql.gz | psql postgresql://clew:PASSWORD@localhost/clew`
- Add to DEPLOY.md under Day-to-Day Commands

**When to upgrade:** when monthly recurring revenue justifies it, migrate Postgres to RDS with automated daily snapshots and point-in-time recovery. On a t3.small with < 10 customers, pg_dump to S3 is sufficient and costs nothing.

---

### 48. Internal ops panel

With no internal view you cannot operate outreach or monitor trial conversions without psql queries. For a B2B product with manual pilot outreach this is a real operational gap from the first paying customer.

**MVP approach — read-only protected route, no frontend build needed:**

- `GET /admin/orgs` — returns paginated list of all orgs with: name, owner email, tier, trial_ends_at, billing_provider, s3_connected (bool), last_scan_completed_at, monthly_requests_processed, created_at
- `GET /admin/orgs/{org_id}` — single org detail + member list + recent verdicts count
- Protected by a separate `ADMIN_API_KEY` env var (not a user session) — `Authorization: Bearer $ADMIN_API_KEY` header
- Consume it from your laptop via curl or import into a tool like Bruno/Postman
- Do not build a UI for this — JSON is sufficient for one operator
- Key views needed operationally:
  - Pilots expiring in the next 7 days (filter `trial_ends_at < now() + 7d` and `billing_provider IN ('pilot', null)`)
  - Orgs with S3 connected but no verdicts in 48h (potential setup issues to proactively reach out about)
  - Conversion rate: trial orgs that became paying

---

### 49. Staging environment

One bad deploy to a live customer's monitoring dashboard is a trust problem that is hard to recover from.

**MVP approach — same EC2 instance, different ports and database:**

- Not a separate server — just a second set of PM2 processes on different ports with a separate Postgres database (`clew_staging`) and a separate `.env.staging`
- Nginx: add a `staging.clewsec.com` server block pointing to the staging ports
- Deploy workflow: push to GitHub → pull on EC2 → run migrations against `clew_staging` → start staging processes → test manually → if clean, run against production
- This is enough for a single-developer team. A full CI/CD pipeline comes later.
- Add `clew-api-staging`, `clew-frontend-staging`, `clew-worker-staging` entries to `ecosystem.config.js`

---

### 50. Uptime + worker health monitoring

A paying customer's scans silently stopping while the EC2 is up is worse than the server being down — you won't know until they email you. Three layers needed, all free tier, no infrastructure to manage:

**Layer 1 — HTTP uptime (UptimeRobot, free):**
- Monitor `https://clewsec.com/health` every 5 minutes
- Email alert on down → catches "server is dead"
- Setup: 1 minute at uptimerobot.com, no code

**Layer 2 — Beat task heartbeat (Cronitor, free tier: 5 monitors):**
- Catches "server is up but Celery Beat/workers stopped" — the failure mode UptimeRobot misses entirely
- Add `CRONITOR_URL` env var; at the end of `process_logs` task (in the `finally` block, after lock release), add: `if settings.CRONITOR_URL: requests.get(settings.CRONITOR_URL, timeout=3, raise_exception=False)`
- Configure the Cronitor monitor with a 25-minute window (slightly over the 15-min poll interval) — if no ping arrives in 25 minutes, Cronitor emails you
- This is a 2-line addition to `process_logs.py`

**Layer 3 — Exception tracking (Sentry, see item 46):**
- Catches "server is up, tasks are running, but there are errors"

Together these three cover every realistic production failure mode for the MVP. Grafana/CloudWatch dashboards are justified at 5+ paying customers — not before.

**What to add to DEPLOY.md:** a "Monitoring setup" section under Phase 4 (after environment is live) with the UptimeRobot URL and a note to set `CRONITOR_URL` in the production `.env`.

---

## Phase 10 — Post-MVP

### 41. Verdict export (CSV)

- Add `GET /verdicts/export?format=csv&days=30` endpoint
- Stream CSV directly — do not buffer entire result in memory
- Gate behind starter+ tier

---

### 42. Replace IAM key ingestion with cross-account IAM role

Currently clients paste their AWS access keys into settings — bad security practice.
- Better: clients create an IAM role in their account that trusts Clew's AWS account
- Clew assumes the role via STS `AssumeRole` to read their S3 bucket
- No long-lived credentials stored; rotate by re-issuing the role
- Update settings UI and docs accordingly

---

### 43. Beat scheduler — only poll orgs with S3 configured

After org refactor: fan out per org, skip orgs with no `s3_bucket` set. Add jitter to spread load when org count grows.

---

### 44. Engine — swap Ollama to Groq in production

Currently the engine uses a local Ollama server (qwen2.5:7b). For production EC2 (no GPU), Groq is faster and cheaper. Make LLM provider configurable via env: `LLM_PROVIDER=groq|ollama`

---

### 45. Engine cold-start calibration for real traffic

Agent thresholds (e.g. `HIGH_RATE_ABSOLUTE = 450` in VolumeAgent) were calibrated against CICIDS 2017 with 500-record windows. Real customer traffic will vary wildly — a fintech partner might legitimately send 5,000 req/min from one IP.

Fix: on first S3 connection, run a calibration pass on the last 24h of logs silently (no verdicts written) to seed the LTM baseline before live detection starts. Surface a "Calibrating…" state in the dashboard during warmup. (Separate from the 7-day historical ingestion window — this is about warming detection thresholds, not ingesting logs for verdict output.)

---

### 46. Observability

- Structured JSON logging in the API and workers (currently `print` / default logging)
- Centralise to CloudWatch Logs or a log aggregator
- Add Sentry DSN for exception tracking (backend + frontend)

---

## Feature / Tier Matrix

What exists today vs. what is planned, split by tier.
Legend: ✅ built + enforced | 🔧 built but not tier-gated | 📋 planned | ❌ not planned

### Free — $0 / ₹0 (removed) — replaced by 30-day no-card trial for all signups
| Feature | Status | Notes |
|---|---|---|
| S3 log ingestion (API Gateway + ALB) | ✅ | |
| 7-agent threat detection engine | ✅ | |
| Dashboard (summary, trend chart, top IPs) | ✅ | |
| 7-day threat history | 📋 | UI shows all history; need to enforce cutoff |
| Top 10 threat IPs only | 📋 | UI shows all IPs; need to enforce limit |
| Email verification + MFA (TOTP) | ✅ | |
| Up to 2M API calls/month processed | 📋 | No usage metering yet |

### Starter — $39 / ₹2,999 per month  |  **EARLY ACCESS pricing until 2027**  |  annual: 2 months free (~17% off), shown as "$32/mo billed annually" / "₹2,499/mo billed annually"
Monitoring only. No blocking. The "does it work" tier — see what's hitting your APIs, get email alerts, validate the product. Below any approval threshold at an Indian startup.
| Feature | Status | Notes |
|---|---|---|
| Everything in Free | ✅ | |
| Threat history: 90 days | 📋 | No cutoff enforcement yet |
| Email alerts on high/critical verdicts | ✅ | Enforced in `send_alerts.py` |
| Full IP intelligence table (unlimited IPs) | 📋 | No limit enforcement yet |
| Verdict export (CSV) | 📋 | Not built |
| Up to 10M API calls/month | 📋 | No metering |
| API keys (read-only scope) | 📋 | Not built |

### Growth — $69 / ₹4,999 per month  |  **EARLY ACCESS pricing until 2027**  |  annual: 2 months free (~17% off), shown as "$57/mo billed annually" / "₹4,166/mo billed annually"
The real product. Detection + blocking. WAF + Cloudflare. This is where Clew actually stops attacks, not just reports them.
| Feature | Status | Notes |
|---|---|---|
| Everything in Starter | ✅ | |
| Threat history: 1 year | 📋 | No cutoff enforcement yet |
| Auto WAF (AWS) IP blocking | ✅ | Enforced in `push_blocks.py` |
| Cloudflare IP blocking | ✅ | Enforced in `push_blocks.py` |
| Manual block / unblock from dashboard | ✅ | Enforced in `verdicts.py` |
| Slack / webhook alerts | 📋 | Pricing page lists it; not built |
| Up to 50M API calls/month | 📋 | No metering |
| API keys (read + block scope) | 📋 | Not built |
| Up to 10 team members | 📋 | Depends on RBAC refactor |

### Pro — $129 / ₹9,999 per month  |  **EARLY ACCESS pricing until 2027**  |  annual: 2 months free (~17% off), shown as "$107/mo billed annually" / "₹8,333/mo billed annually"

**Key differentiator vs Growth:** Growth = detection + blocking (see it and stop it). Pro = everything in Growth + Groq LLM verdict explanations + custom thresholds + custom allowlists + multiple environments (prod/staging) + SIEM integrations + compliance reports + audit log + PagerDuty. Growth is operational. Pro is analytical, customisable, and compliance-ready.
| Feature | Status | Notes |
|---|---|---|
| Everything in Growth | ✅ | |
| Threat history: 3 years | 📋 | No cutoff enforcement yet |
| Groq AI explanations on verdicts | 📋 | Not built (item 33) |
| Custom detection thresholds (per-endpoint, per-IP) | 📋 | Not built — no UI or backend |
| Custom allowlists (IP ranges, user-agents, paths) | 📋 | Not built |
| Multiple S3 sources per org (multi-env: prod/staging) | 📋 | Not built — schema supports one bucket per org |
| SIEM integrations: Datadog / Splunk / Elastic webhook | 📋 | Not built |
| Org-level audit log (who blocked/unblocked/changed config) | 📋 | Not built — critical for compliance |
| Exportable compliance reports (PDF/CSV, date-ranged) | 📋 | Not built |
| PagerDuty integration | 📋 | Not built |
| Up to 200M API calls/month | 📋 | No metering |
| API keys (full scope incl. config:write, blocks:write) | 📋 | Not built |
| Unlimited team members | 📋 | Depends on org/RBAC refactor |
| Priority support (24h SLA) | ❌ | Manual/sales process |
| Dedicated onboarding | ❌ | Manual/sales process |

### Enterprise — custom pricing
| Feature | Status | Notes |
|---|---|---|
| Everything in Pro | — | |
| Multi-region support | 📋 | Not built |
| Custom integrations | ❌ | Professional services |
| SLA guarantee | ❌ | Legal/contracts |
| Dedicated infrastructure | 📋 | Separate deployment |
| Cross-account IAM role ingestion | 📋 | See item 42 |
| Inline reverse proxy (future) | 📋 | Enterprise-only when built |

### Clew Audit — $599 / ₹49,999 (one-time, Early Access)
Point-in-time manual audit. Includes a written report with findings and remediation recommendations, plus a follow-up call. Requested via `mailto:` CTA — no automated flow needed.

### Gaps vs. pricing page claims (billing integrity issues)
The following are advertised on the pricing page but **not enforced or built**:
- `7-day threat history limit` on Free — need to add cutoff in dashboard + verdicts queries
- `Top 10 IPs limit` on Free — need limit in IPs endpoint
- History cutoffs (90 days / 1 year / 3 years / unlimited) — no enforcement yet; all tiers see all data
- `2M / 10M / 50M / 200M call volume limits` — no metering at all (see item 30)
- `Slack alerts` listed under Growth — not built (see item 34)
- `Custom thresholds` listed under Pro — not built

### Annual billing — SKUs to create
When the annual toggle is added to the pricing page:
- Show monthly equivalent (e.g. "$82/mo, billed annually")
- Razorpay: create 6 annual Plans in the dashboard (one per tier)
- Stripe: create 6 annual Price objects (interval=year) in the dashboard
- Same checkout flow, different Price/Plan IDs based on toggle state

### Pro tier — features to add to the pricing page
The pricing page card must communicate the Growth → Pro jump clearly: Growth stops attacks, Pro explains them and lets you customise everything. Add to the `Pricing.tsx` TIERS array under Pro:
- Groq AI verdict explanations
- Custom detection thresholds per endpoint
- Custom allowlists (IP ranges, user-agents, paths)
- Multiple environments (prod + staging)
- SIEM integrations (Datadog, Splunk, Elastic)
- Organisation-level audit log
- Exportable compliance reports (PDF/CSV)
- PagerDuty integration
- Unlimited team seats (Growth = 10 seats)
- Priority support with 24h SLA
