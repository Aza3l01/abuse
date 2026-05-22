# Clew — Open Work Items

## CRITICAL (architectural — do before any real customers)

### 1. Organisation / Multi-user refactor
- Add `organizations` table — holds company name, S3 config, WAF config, Stripe/billing, tier, alert_email
- Add `organization_members` table — links `Client` (login) to `Organization` with role: `owner | admin | viewer`
- Move off `Client`: s3_bucket, s3_prefix, log_format, aws_region, waf_ip_set_id, cloudflare_*, alert_email, tier, stripe_*, tier_expires_at, last_processed_key
- Rekey all FK columns: `Verdict.client_id` → `org_id`, `IpMemory.client_id` → `org_id`, `AlertSent.client_id` → `org_id`
- Update `api/deps.py` — add `get_current_org()` resolved from JWT → client → membership
- Update all route query filters (verdicts, dashboard, ips, clients, billing) to use `org_id`
- Update workers (process_logs, send_alerts, push_blocks) to use `org_id`
- Update engine normalizer `client_id` param → `org_id`
- Registration creates both `Client` + `Organization` + `OrganizationMember(role=owner)` atomically
- Write Alembic migration — clean drop+recreate (no data to migrate)
- Write member invite flow: POST /org/invite → email link → accept → OrganizationMember row

### 2. Role-based access control (RBAC)
Roles per org membership:
- `owner` — full access, billing, invite/remove members, delete org
- `admin` — full access except billing and org deletion
- `viewer` — read-only: dashboard, verdicts, IPs; cannot change config or trigger blocks
- Enforce in `get_current_org()` via role checks on each route
- Expose role in `/auth/me` response
- Settings page shows member list with roles; owner can change roles / remove members

---

## HIGH PRIORITY (before launch)

### 3. Registration — collect more useful info
Current: email, password, company name only. Add:
- `full_name` (user's name, not company)
- `job_title` — dropdown: Founder / CTO / Security Engineer / DevOps / Other
- `company_size` — dropdown: 1–10 / 11–50 / 51–200 / 200+
- `use_case` — dropdown: API abuse / Bot detection / DDoS protection / All of the above
- `how_did_you_hear` — optional: Google / Twitter/X / LinkedIn / Word of mouth / Other
- Terms of Service checkbox (required) + Privacy Policy checkbox (required)
- Store `full_name`, `job_title`, `company_size` on `Client`; store `use_case`, `how_did_you_hear` on `Organization`

### 4. Terms of Service and Privacy Policy pages
- Create `/terms` page — placeholder with "Terms coming soon via Termly" or full Termly embed when ready
- Create `/privacy` page — same
- Add links to both in the Footer component
- Add checkbox to registration: "I agree to the Terms of Service and Privacy Policy" (required field, validated on submit)
- Auth routes: store `tos_accepted_at` timestamp on `Client` when they register

### 5. Groq integration for explainable verdict summaries (Pro tier only)
- The LLM client (`engine/source/llm/client.py`) already supports any OpenAI-compatible endpoint
- Add `GROQ_API_KEY` to `.env`
- Add Groq as the production LLM: base_url=`https://api.groq.com/openai/v1`, model=`llama-3.3-70b-versatile`
- In `engine/source/pipeline/run.py` — after verdict is produced, if tier == "pro": call Groq to generate a human-readable explanation paragraph (1–3 sentences) stored in `verdicts.explanation`
- Gate the `explanation` field in the verdicts API response behind tier check
- Show explanation in the verdict detail UI (expandable card) only for pro users
- Fall back to Ollama/local for dev (DEBUG=1) so no API key needed locally

### 7. Webhook / Slack / PagerDuty alert channels
- Today only email alerts via SES — not enough for real security teams
- Add `alert_webhook_url` field on `Organization`
- Send JSON POST on high/critical verdicts (org-level toggle: all severities vs high+ only)
- Auto-detect Slack incoming webhook URL format → send formatted Slack Block Kit message with verdict details
- PagerDuty Events API v2 integration (optional, behind a separate `pagerduty_routing_key` field)
- Show per-channel on/off toggles in the settings dashboard
- Celery task structure already exists in `send_alerts.py` — extend it
- Gate: email = starter+, webhook = growth+, PagerDuty = pro

### 8. Public customer-facing API + API keys
- Clew is a security product — customers will want to pull verdicts into their own SIEM, Splunk, Datadog, etc.
- Without this, the dashboard is the only way to see data — that's a blocker for enterprise buyers
- Add `api_keys` table: `id`, `org_id`, `name`, `key_hash` (SHA-256), `scopes` (JSON list), `last_used_at`, `expires_at`, `revoked`
- Accept `Authorization: Bearer <key>` in addition to session cookies across all routes
- Scopes: `verdicts:read`, `ips:read`, `config:write`, `blocks:write`
- Settings dashboard: create named keys, set expiry, copy once, revoke
- Public API base: `https://api.clewsec.com/v1/` (version prefix — current routes are unversioned, add `/v1` prefix or keep both)
- Endpoints customers will actually use:
  - `GET /v1/verdicts` — filterable by severity, date range, IP
  - `GET /v1/verdicts/{id}` — full detail incl. explanation
  - `GET /v1/ips` — IP intelligence table
  - `POST /v1/ips/{ip}/block` — manually trigger a block
  - `POST /v1/ips/{ip}/unblock`
  - `GET /v1/org` — read org config
  - `PATCH /v1/org` — update S3, WAF, alert settings
- Write an OpenAPI spec and publish it in the docs (auto-generated from FastAPI if DEBUG=1 locally, hand-curated in docs site)
- Eventually: Python SDK (`pip install clew`) wrapping the REST API

### 6. In-product documentation / integration guide
- Create `/docs` route in Next.js (separate from the marketing site)
- Design matches the existing design system (same tokens, fonts, no external UI lib)
- Sections:
  - Quick Start (5 minutes to first verdict)
  - How to enable API Gateway access logs and point them at S3
  - How to enable ALB access logs and point them at S3
  - Required IAM permissions (cross-account S3 read policy snippet)
  - Setting up the Clew IAM cross-account role (vs. access keys)
  - Log formats supported (JSON / CLF examples)
  - Setting up WAF IP set blocking
  - Setting up Cloudflare IP blocking
  - Understanding verdicts and severity levels
  - Alert emails — what triggers them, how to change the address
  - Team members — inviting colleagues (once RBAC is done)
  - FAQ
- Add "Docs" link to Navbar

---

## MEDIUM PRIORITY (post-launch)

### 7. Replace IAM key ingestion with cross-account IAM role
- Currently clients paste their AWS access keys into settings — bad security practice
- Better: clients create an IAM role in their account that trusts Clew's AWS account
- Clew assumes the role via STS `AssumeRole` to read their S3 bucket
- No long-lived credentials stored; rotate by re-issuing the role
- Update settings UI and docs accordingly

### 8. Webhook / Slack alert channel
- MOVED — see High Priority item 7

### 9. Verdict export
- Add `GET /verdicts/export?format=csv&days=30` endpoint
- Stream CSV directly (don't buffer entire result in memory)
- Gate behind starter+ tier

### 10. Public customer API + SDK
- MOVED — see High Priority item 8

### 11. Beat scheduler — only poll clients with S3 configured
- `workers/beat.py` fans out a task per client
- After org refactor: fan out per org, skip orgs with no s3_bucket set
- Add jitter to spread load when org count grows

### 12. Dashboard — missing UI pages
- No `/dashboard/alerts` page exists in the file tree — `alerts/` folder exists but needs building
- Verdict detail page (`/dashboard/verdicts/[id]`) — currently clicking a verdict does nothing
- Blocked IPs page — show which IPs are currently blocked across WAF + Cloudflare

### 9. Email templates — move to HTML
- All emails are plain text (`api/auth_utils.py`) — looks unprofessional and untrustworthy
- Add HTML versions with the Clew wordmark, brand colours, clean layout
- Templates needed: email verification, password reset, MFA enabled, alert (high/critical verdict), OAuth account linked, welcome (post-verification)
- Keep plain-text fallback in all emails for spam filter compatibility
- Use inline CSS only (Gmail strips `<style>` blocks)

---

## LOW PRIORITY / NICE TO HAVE

### 14. Onboarding flow post-registration
- After email verification, land on a guided setup wizard (not the empty dashboard)
- Steps: Connect S3 → choose log format → test connection → see first verdict

### 15. Usage / quota display
- Show in the dashboard: "X / 200 emails today", requests processed this month
- Relevant when free tier users approach limits

### 16. Engine — swap Ollama to Groq in production
- Currently the engine uses a local Ollama server (qwen2.5:7b)
- For production EC2 (no GPU), Groq is faster and cheaper
- Make LLM provider configurable via env: `LLM_PROVIDER=groq|ollama`

### 17. Security hardening
- Add `Content-Security-Policy` header in Nginx config
- Add `Permissions-Policy` and `Referrer-Policy` headers
- Rate-limit `/auth/register` more aggressively (currently 5/hour — fine; confirm on staging)
- Consider CAPTCHA (hCaptcha / Cloudflare Turnstile) on register + forgot-password

### 19. Engine cold-start calibration for real traffic
- Agent thresholds (e.g. `HIGH_RATE_ABSOLUTE = 450` in VolumeAgent) were calibrated against CICIDS 2017 dataset with 500-record windows
- Real customer traffic will vary wildly: a fintech partner might legitimately send 5000 req/min from one IP; a startup's entire prod traffic may be 50 req/min
- Until LTM warms up (~15 batches ≈ ~3.75 hrs at 15-min polling), cold-start values run and will produce false positives/negatives on real traffic
- Fix: on first S3 connection, run a "calibration pass" on the last 24h of logs silently (no verdicts written) to seed the LTM baseline before live detection starts
- Also: surface a "Calibrating…" state in the dashboard during warmup so customers understand why they see no verdicts yet
- This is different from "custom thresholds" (Pro) — this is making the default behaviour correct for any traffic profile

### 20. Observability
- Structured JSON logging in the API and workers (currently `print` / default logging)
- Centralise to CloudWatch Logs or a log aggregator
- Add a Sentry DSN for exception tracking (backend + frontend)

---

## FEATURE / TIER MATRIX

What exists today vs. what is planned, split by tier.
Legend: ✅ built + enforced | 🔧 built but not tier-gated | 📋 planned | ❌ not planned

### Free — $0 / ₹0
| Feature | Status | Notes |
|---|---|---|
| S3 log ingestion (API Gateway + ALB) | ✅ | |
| 7-agent threat detection engine | ✅ | |
| Dashboard (summary, trend chart, top IPs) | ✅ | |
| 7-day threat history | 📋 | UI shows all history; need to enforce cutoff |
| Top 10 threat IPs only | 📋 | UI shows all IPs; need to enforce limit |
| Email verification + MFA (TOTP) | ✅ | |
| Google / GitHub / Microsoft OAuth login | 🔧 | Built, not gated |
| Up to 2M API calls/month processed | 📋 | No usage metering yet |

### Starter — $99 / ₹6,999
| Feature | Status | Notes |
|---|---|---|
| Everything in Free | ✅ | |
| Full threat history (unlimited days) | 📋 | No cutoff enforcement yet |
| Email alerts on high/critical verdicts | ✅ | Enforced in `send_alerts.py` |
| Full IP intelligence table (unlimited IPs) | 📋 | No limit enforcement yet |
| Verdict export (CSV) | 📋 | Not built |
| Up to 10M API calls/month | 📋 | No metering |
| API keys (read-only scope) | 📋 | Not built |

### Growth — $249 / ₹14,999
| Feature | Status | Notes |
|---|---|---|
| Everything in Starter | ✅ | |
| Auto WAF (AWS) IP blocking | ✅ | Enforced in `push_blocks.py` |
| Cloudflare IP blocking | ✅ | Enforced in `push_blocks.py` |
| Manual block / unblock from dashboard | ✅ | Enforced in `verdicts.py` |
| Slack / webhook alerts | 📋 | Pricing page lists it; not built |
| Up to 50M API calls/month | 📋 | No metering |
| API keys (read + block scope) | 📋 | Not built |
| Up to 10 team members | 📋 | Depends on RBAC refactor |

### Pro — $449 / ₹29,999
| Feature | Status | Notes |
|---|---|---|
| Everything in Growth | ✅ | |
| Groq AI explanations on verdicts | 📋 | Not built (TODO #5) |
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
| Dedicated infrastructure | 📋 | Would require separate deployment |
| Cross-account IAM role ingestion | 📋 | See TODO medium priority #7 |

### Pro tier — features to add to the pricing page
Pro currently advertises too little for its price. The following should be added to the `Pricing.tsx` TIERS array under Pro:
- Custom detection thresholds
- Custom allowlists
- Multiple environments (prod + staging)
- SIEM integrations (Datadog, Splunk, Elastic)
- Audit log
- Compliance reports
- PagerDuty
- Unlimited team seats (growth = 10, pro = unlimited)
- Priority support with 24h SLA

### Gaps vs. pricing page claims
The following are advertised on the pricing page but **not enforced or built**:
- `7-day threat history limit` on Free — need to add cutoff in dashboard + verdicts queries
- `Top 10 IPs limit` on Free — need limit in IPs endpoint
- `2M / 10M / 50M / 200M call volume limits` — no metering at all; anyone on any tier can process unlimited logs
- `Slack alerts` listed under Growth — not built
- `Custom thresholds` listed under Pro — not built

These are billing integrity issues: customers could stay on Free forever and get Growth-level access.


