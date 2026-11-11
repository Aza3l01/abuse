# Clew README

This document is the single reference for a developer working on Clew.
Covers what the product is, how the codebase is organised, how to run everything
locally, how every component works, and how to do common development tasks.

Read top to bottom the first time. Use as a reference after that.

---

## What Is Clew

Clew is a B2B SaaS product that monitors API gateway logs for abuse and attack
patterns, detects threats using a multi-agent AI engine, and can automatically
block malicious IPs via AWS WAF or Cloudflare.

**Zero-integration positioning:** the customer gives Clew read-only S3 access to
their existing AWS API Gateway or ALB logs. No code changes, no proxy, no SDK.
Clew polls S3 every 15 minutes, runs the detection engine, and surfaces findings
in a web dashboard.

**Target customers:** Seed, Series A SaaS companies and SMBs with public APIs and no
dedicated security team.

---

## Repository Structure

```
abuse/                         <- project root (repo: "abuse", product: Clew)
├── api/                       <- FastAPI backend
│   ├── main.py                <- app entry point, CORS, routers wired in
│   ├── deps.py                <- get_db(), get_current_client(), get_current_org(), require_role()
│   ├── auth_utils.py          <- hashing, JWT, cookies, OTP, Resend email, Turnstile verification
│   ├── limiter.py             <- shared slowapi rate limiter (Redis-backed, shared across workers)
│   ├── tiers.py               <- shared tier constants (blocking, volume caps, retention, LLM)
│   ├── aws.py                 <- aws_session_for_org(): cross-account sts:AssumeRole sessions
│   └── routes/
│       ├── auth.py            <- register/login/MFA/sessions/password/account deletion
│       ├── clients.py         <- GET/PATCH /clients/me (org config), blocking ToS, onboarding state
│       ├── verdicts.py        <- list/detail/manual-block/block/unblock/threat-types
│       ├── dashboard.py       <- GET /dashboard/summary
│       ├── ips.py             <- GET /ips, POST /ips/{ip}/unblock
│       ├── billing.py         <- Razorpay Orders (payments, refunds, cancel, details); Stripe code kept but unused
│       │                         (payment rules live in api/billing_payments.py + api/billing_rules.py)
│       ├── org.py             <- create org, invites, team members, role changes, ownership transfer
│       ├── settings.py        <- POST /settings/test-waf, /settings/test-cloudflare
│       ├── newsletter.py      <- POST /newsletter/subscribe, /newsletter/confirm (Resend Audiences)
│       └── alerts.py          <- GET /alerts (delivery log), POST /alerts/test
│
├── db/
│   ├── models.py              <- all SQLAlchemy ORM models (Client, Organization, ...)
│   ├── session.py             <- engine + SessionLocal factory
│   └── migrations/versions/   <- 18 revisions, see `alembic history` for the current chain
│
├── detection/                 <- AI detection engine
│   ├── schemas/models.py      <- LogRecord pydantic model
│   ├── datasets/               <- CICIDS2017 eval data + GeoLite2 .mmdb files
│   ├── evaluate.py             <- offline eval harness (F1/precision/recall vs. CICIDS ground truth)
│   └── engine/                <- engine package; `from engine.xxx` imports resolve here
│       ├── agents/            <- 6 active detection agents + 1 passive (KnowledgeAgent)
│       ├── coordinator/       <- MetaAgentOrchestrator (fusion + XGB)
│       ├── memory/
│       │   ├── shared_memory.py       <- in-process STM + LTM base class
│       │   └── product_memory.py      <- Redis-backed LTM for production
│       ├── pipeline/run.py            <- run_pipeline(), Celery entry point
│       ├── ingestion/
│       │   ├── s3_reader.py           <- list + download S3 log objects
│       │   ├── apigw_parser.py        <- AWS API Gateway log parser
│       │   ├── alb_parser.py          <- AWS ALB log parser
│       │   └── normalizer.py          <- routes to correct parser, batches, source_key tagging
│       └── tests/                     <- run_tests.py (unit), test_pipeline.py (pipeline)
│
├── workers/
│   ├── celery_app.py          <- Celery app instance + config
│   ├── beat.py                <- 8-entry schedule, see the Celery Pipeline section
│   ├── tests/                 <- test_process_logs.py (custom runner, not pytest)
│   └── tasks/
│       ├── process_logs.py            <- S3 -> detect -> verdicts + ip_memory (the main task)
│       ├── send_alerts.py             <- Resend email alerts, severity-threshold gated
│       ├── push_blocks.py             <- WAF / Cloudflare IP block tasks
│       ├── trial_reminders.py         <- 5d/2d trial-ending emails + expired-trial tier revert
│       ├── reset_usage_counters.py    <- monthly call-volume counter reset (1st of month)
│       ├── purge_expired_data.py      <- tiered retention purge (daily)
│       └── purge_deleted_accounts.py  <- hard-deletes orgs/clients 30 days after soft-delete
│
├── blocking/
│   ├── aws_waf.py             <- add/remove IPs from WAF IP sets
│   └── cloudflare.py         <- block/unblock IPs via Cloudflare API
│
├── frontend/                  <- Next.js 16 app router
│   └── src/
│       ├── app/
│       │   ├── layout.tsx             <- root layout, fonts, OG metadata
│       │   ├── page.tsx               <- homepage (marketing)
│       │   ├── pricing/page.tsx       <- standalone /pricing route
│       │   ├── docs/page.tsx          <- public documentation (LegalLayout scroll-spy TOC)
│       │   ├── login/, register/      <- sign in, create account (Turnstile-gated)
│       │   ├── verify-email/          <- OTP confirmation
│       │   ├── forgot-password/, reset-password/  <- Turnstile-gated reset flow
│       │   ├── accept-invite/         <- team invite acceptance (new or existing account)
│       │   ├── newsletter/confirm/    <- double opt-in confirmation landing page
│       │   ├── legal/                 <- terms, privacy, dpa, subscription-agreement, refund-policy
│       │   └── dashboard/
│       │       ├── layout.tsx         <- sidebar + StatusHeader + banners + DashboardGate wrapper
│       │       ├── page.tsx           <- overview (stats, chart, top IPs, scanning banner)
│       │       ├── alerts/page.tsx    <- Verdicts + Notifications tabs
│       │       ├── ips/page.tsx       <- All IPs + Blocked tabs
│       │       ├── verdicts/[id]/     <- verdict detail (agent scores, raw logs, AI analysis)
│       │       └── settings/page.tsx  <- S3/WAF/Cloudflare config, MFA, team, billing
│       ├── components/
│       │   ├── home/                  <- Hero, CostCalculator, HowItWorks, AgentsSection, Pricing
│       │   ├── layout/                <- Navbar, Footer (LinkedIn + Maps icons, NewsletterForm)
│       │   ├── legal/                 <- LegalLayout (scroll-spy TOC sidebar, reused by /docs)
│       │   ├── dashboard/             <- Sidebar, StatusHeader, TeamMembers, tab components,
│       │   │                             OnboardingModal, GuidedOnboardingButton, LogSourceWizard,
│       │   │                             PlanCheckoutTrigger, Trial/Usage/MfaNudge banners
│       │   ├── auth/                  <- AuthLayout, Turnstile widget wrapper
│       │   └── providers/             <- ThemeProvider (next-themes)
│       ├── lib/                       <- api.ts (apiFetch w/ silent refresh), pricing.ts,
│       │                                 onboarding.ts, razorpay.ts, passwordStrength.ts
│       └── proxy.ts                   <- Edge auth gatekeeper (Next.js 16's middleware.ts)
│
├── docker/
│   ├── docker-compose.yml     <- local Postgres + Redis
│   ├── nginx.conf             <- production Nginx config (CSP, security headers)
│   └── ecosystem.config.js    <- PM2 process config, copy to repo root when deploying
│
├── scripts/
│   ├── download_geoip.sh      <- fetches GeoLite2-City + GeoLite2-ASN .mmdb files
│   └── create_staff_user.py   <- creates a staff user + TOTP for the internal ops panel (CLI only)
│
├── .env.example               <- all env vars with descriptions
├── requirements.txt           <- Python dependencies
└── alembic.ini                <- Alembic config
```

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Backend API | FastAPI + Python 3.11 | Async, Pydantic validation, auto-docs |
| Database | PostgreSQL 16 | JSONB for agent arrays, TIMESTAMPTZ everywhere |
| Cache / queue | Redis 7 | Celery broker, rate-limit counters, LTM state |
| Background jobs | Celery + Celery Beat | S3 polling every 15 min, alerts, blocking |
| Frontend | Next.js 16 (App Router) | Server components, Edge middleware |
| Styling | Tailwind + CSS variables | No component library, custom design system |
| Auth | httpOnly JWTs + bcrypt | Cookies unreadable by JS — no XSS token theft |
| Email | AWS SES (via Resend) | Transactional verification + alert emails |
| Billing | Razorpay (USD default, INR for India) | Stripe is not used; the old Stripe code is kept for a possible later provider |
| Detection | Custom multi-agent engine | Validated on CICIDS2017, CTU-13, CSIC |
| Blocking | AWS WAF v2 + Cloudflare | Growth/Pro tiers |
| Process manager | PM2 | Manages all 4 server processes |
| Web server | Nginx | Reverse proxy + static cache |

---

## Running Locally — Quick Start

### 1. Prerequisites
- Docker + Docker Compose
- Python 3.11
- Node.js 20+

### 2. Clone and configure env
```bash
git clone <repo> clew && cd clew (abuse not clew)
cp .env.example .env
```

Fill in at minimum:
```bash
# Generate JWT secret
openssl rand -hex 64

# Generate TOTP Fernet key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set `DATABASE_URL=postgresql://clew:password@localhost:5432/clew`,
`REDIS_URL=redis://localhost:6379/0`, and the two generated secrets.

Add `LOG_EMAILS=1` to print all outbound emails to terminal instead of sending
via Resend — required for local development unless you have a Resend API key.

Registration and forgot-password require a Cloudflare Turnstile CAPTCHA to
pass. Set `TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA` in
`.env` (backend) and `NEXT_PUBLIC_TURNSTILE_SITE_KEY=1x00000000000000000000AA`
in `frontend/.env.local` (frontend): Cloudflare's official "always passes"
test keys, documented at
[developers.cloudflare.com/turnstile/troubleshooting/testing](https://developers.cloudflare.com/turnstile/troubleshooting/testing/).
Without a real or test key, `verify_turnstile_token()` fails closed and every
registration/forgot-password request is rejected.

**If `.env` already holds real production secrets** (e.g. this repo is
already deployed and you don't want to touch the live values while testing
locally), create a gitignored `.env.local` at the repo root instead of
editing `.env` directly. `api/main.py`, `workers/celery_app.py`, and
`db/migrations/env.py` all load `.env` first, then `.env.local` with
`override=True`, so anything set there wins locally without changing `.env`.
Put the local-only `DATABASE_URL`, `DASHBOARD_URL=http://dashboard.localhost:3000`,
`HOME_URL=http://localhost:3000`, `COOKIE_DOMAIN=` (blank), `DEBUG=1`, and the Turnstile test key above into
`.env.local` instead.

### 3. Start infrastructure
```bash
docker compose -f docker/docker-compose.yml up -d
```
Postgres on `:5432`, Redis on `:6379`.

### 4. Python backend
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Apply migrations (db/migrations/env.py loads .env/.env.local itself)
alembic upgrade head

# Start API with hot reload (api/main.py loads .env/.env.local itself)
uvicorn api.main:app --reload --port 8000
```

API: `http://localhost:8000` | Docs: `http://localhost:8000/docs`

Don't manually `source .env` first, some values (like a password containing
shell-special characters) will make bash choke with a syntax error. It's also
unnecessary: every entry point above already loads `.env`/`.env.local` itself
via python-dotenv, which parses the file properly instead of executing it as
a shell script.

### 5. Celery workers
```bash
# Terminal 2: Worker
source .venv/bin/activate
celery -A workers.celery_app worker --loglevel=info

# Terminal 3: Beat scheduler
source .venv/bin/activate
celery -A workers.celery_app beat --loglevel=info
```

### 6. Frontend
```bash
cd frontend
# Copy frontend/.env.local.example to frontend/.env.local and set JWT_SECRET to
# the same value as the backend .env. The rest of the defaults work for dev
# (NEXT_PUBLIC_API_URL=/api, DASHBOARD_HOST=dashboard.localhost:3000, ...).
npm install
npm run dev
```

Marketing site: `http://localhost:3000`
App (dashboard, login, register): `http://dashboard.localhost:3000` (browsers
resolve `*.localhost` to 127.0.0.1, no hosts-file edit needed).

The browser calls the API same-origin at `/api/*`. In dev a Next.js rewrite
(`next.config.ts`, development only) forwards it to `API_INTERNAL_URL`
(default `http://127.0.0.1:8000`). In production nginx does it instead.

### Hosts and environment variables

| Host | Serves |
|---|---|
| `www.clewsec.com` | Marketing site (canonical), `/api/` proxied by nginx |
| `clewsec.com` | 301 to `https://www.clewsec.com` |
| `dashboard.clewsec.com` | The app at the root path (no `/dashboard` prefix), `/api/` proxied by nginx |
| `api.clewsec.com` | FastAPI directly, for webhooks and the external API only |

The dashboard host is the same Next.js process: `src/proxy.ts` looks at the
Host header and rewrites dashboard-host paths to the `app/dashboard/*` folder.

| Variable | Where | Meaning |
|---|---|---|
| `DASHBOARD_URL` | backend `.env` | Dashboard URL. Emailed app links, billing return URLs, CORS |
| `HOME_URL` | backend `.env` and Next.js server | Home (marketing) URL. Newsletter confirm link; where marketing paths on the dashboard host redirect |
| `COOKIE_DOMAIN` | backend `.env` | Blank in all environments (host-only cookies) |
| `LEGACY_COOKIE_DOMAIN` | backend `.env` | Transition only: old cookie domain to delete (`.clewsec.com`) |
| `NEXT_PUBLIC_API_URL` | Next.js build | `/api` (same-origin) |
| `NEXT_PUBLIC_SITE_URL` | Next.js build | Absolute marketing URL (links, robots, sitemap, metadata) |
| `NEXT_PUBLIC_DASHBOARD_URL` | Next.js build | Absolute dashboard URL (marketing CTAs, redirects) |
| `DASHBOARD_HOST` | Next.js server | Host header value that selects the dashboard (`dashboard.clewsec.com`) |
| `API_INTERNAL_URL` | Next.js server | FastAPI address for the proxy's token refresh and the dev rewrite |

---

## Pilot codes

Admin-generated promo codes (`kind="admin"` on `PromoCode`) are the founder's
manual-outreach pilot mechanism: hand one to a prospect directly, they redeem
it at registration for a 30-day Growth trial. No Razorpay dependency, this
grants a trial, not a charge, so it works whether or not Razorpay is live.
Separate from referral codes (`kind="referral"`), which are auto-generated per
org for self-serve sharing, see `api/referrals.py`.

Generate codes from the internal ops panel (internal.clewsec.com, Pilots
page): 1 to 50 per action, each needs a reason that goes to the audit log. 5
uppercase alphanumeric chars after `CLEW-`, ambiguous characters 0/O/1/I
excluded. Each code is single-use (`max_redemptions=1`); track who you've
handed an unredeemed code to yourself, the system only records
`redeemed_at`/`redeemed_by_org_id` once a code is actually used, not before.
The panel does not enforce a lifetime total.

The panel itself needs a staff user, created only on the server with
`python scripts/create_staff_user.py you@example.com` (password plus TOTP
enrolment). There is no API to create one.

---

## Database

### Tables

Schema is org-centric since Phase 2: a `Client` is a login identity only; an
`Organization` is the tenant that owns S3/blocking/billing config and all
detection data. One `Client` can belong to multiple `Organization`s via
`OrganizationMember` (role: owner/admin/viewer), though in practice one
signup creates one org and stays there.

**`clients`**: login identity only

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `email` | varchar | Unique, indexed. Anonymized to `deleted-{id}@deleted.clew` on account deletion |
| `password_hash` | varchar | bcrypt(sha256-prehash), nullable |
| `full_name` | varchar | |
| `tos_accepted_at` | timestamptz | |
| `email_verified` | bool | Must be True before login allowed |
| `mfa_enabled` / `mfa_secret` | bool / text | Fernet-encrypted TOTP secret |
| `mfa_nudge_dismissed_at` | timestamptz | |
| `verify_token` (+ `verify_token_expires_at`) | text / timestamptz | Email-verification OTP, bcrypt-hashed, never stored raw |
| `reset_token_hash` (+ `reset_token_expires_at`) | text / timestamptz | Password-reset OTP, hashed, never stored raw |
| `deleted_at` | timestamptz | Soft-delete marker; hard-purged 30 days later |

**`organizations`**: one row per tenant, owns everything else

| Column | Type | Notes |
|---|---|---|
| `id` / `company_name` / `domain` | UUID / varchar / varchar | domain drives invite role-ceiling checks |
| `s3_bucket` / `s3_prefix` / `log_format` / `aws_region` | varchar | Customer's log source config |
| `last_processed_key` / `s3_connected_at` | text / timestamptz | Ingestion cursor + first-connect timestamp |
| `s3_status` / `s3_status_message` | varchar / text | Set on log-format auto-detect mismatch |
| `calibration_status` | varchar | `running` / `done` / `failed`, first-connection LTM warmup |
| `last_scan_started_at` / `last_scan_completed_at` / `last_scan_status` / `last_scan_error` | timestamptz / timestamptz / varchar / text | `started_at` also powers the stuck-`in_progress` self-heal sweep |
| `home_country` | varchar(2) | Feeds `GeoIPAgent`'s off-country baseline |
| `aws_role_arn` / `aws_external_id` | varchar | Cross-account `sts:AssumeRole` config. `external_id` is server-generated, read-only, never customer-chosen |
| `waf_ip_set_id` / `cloudflare_zone_id` / `cloudflare_token` / `blocking_tos_accepted_at` | | Blocking config. `cloudflare_token` is Fernet-encrypted at rest |
| `onboarding_completed_at` / `onboarding_dismissed_at` | timestamptz | Guided onboarding state, per organization not per user |
| `alert_email` / `alert_severity_threshold` | varchar | `all` or `high_critical_only` |
| `tier` | varchar | `starter` (free) / `basic` / `growth` / `pro` / `enterprise` |
| `trial_source` / `trial_ends_at` / `pilot_code_used` / `trial_reminder_{5,2}d_sent` | | Promo-code Growth trial only; self-serve signups get no trial |
| `billing_provider` | varchar | `stripe` / `razorpay` / `pilot` |
| `stripe_customer_id` / `stripe_subscription_id` | varchar | Pending live keys |
| `razorpay_customer_id` / `razorpay_subscription_id` / `next_billing_date` / `first_charged_at` | | Billing state. `razorpay_subscription_id` and `razorpay_customer_id` are legacy columns, unused since Phase 4 (Orders have no subscription), kept so no migration is needed |
| `gstin` | varchar | Optional, India only |
| `monthly_requests_processed` / `monthly_requests_reset_at` | int / timestamptz | Live call-volume metering, enforced against `CALL_VOLUME_CAPS` |
| `quota_warning_sent_at` / `quota_exceeded_sent_at` | timestamptz | 80% and 100% soft-limit email idempotency, cleared monthly |
| `deleted_at` | timestamptz | Owner-deletes-account cascades here |

**`organization_members`**: many-to-many, a client's role within an org (`owner` / `admin` / `viewer`, unique on the pair)

**`org_invites`**: single-use directed invite tokens: `invited_email`, `role`, `token_hash`, `expires_at`, `accepted_at`

**`promo_codes`**: launch codes: `code` (unique), linked Stripe coupon / Razorpay offer ID (nullable, filled in later), `redeemed_at`, `redeemed_by_org_id`. A redeemed code grants a 30-day **Growth** trial.

**`processed_webhook_events`**: webhook replay guard: `provider` (`stripe` / `razorpay`) + `event_id`, unique on the pair. Inserted before dispatch; a unique violation returns 200 without re-running side effects. Rows older than 30 days are cleared by the daily purge task.

**`mfa_backup_codes`**: 10 hashed single-use recovery codes per client

**`refresh_tokens`**: one row per active session, SHA-256 hashed, `revoked` flag for the sessions UI

**`verdicts`**: one row per detection result, unique on `(org_id, source_key)` for dedup

Key columns: `ip`, `method`, `endpoint`, `threat_type`, `severity` (critical/high/medium/low),
`confidence` (0–1), `agents_triggered` (JSON, only the triggered subset), `agent_scores`
(JSON, full 6-agent score breakdown incl. non-triggered), `sample_logs` (JSON, up to 5 raw
lines), `explanation`, `blocked`, `cost_prevented`, `source_key` (dedup key).

**`ip_memory`**: one row per `(org_id, ip)` pair (LTM profile)

`first_seen`, `last_seen`, `total_requests`, `threat_count`, `risk_score`, `geo_country`,
`geo_asn_number`, `geo_asn_org`, `waf_blocked` / `cloudflare_blocked` (+ their own
`*_block_error` columns; WAF and Cloudflare are updated independently, one can fail
while the other succeeds).

**`alerts_sent`**: one row per notification attempt: `channel`, `status` (`sent`/`failed`/`bounced`), `delivery_error`

**`scan_runs`**: evidence a batch was scanned and found clean (item 5e); `verdicts` stays
reserved for actual detections, this table powers the "last scanned at" indicator instead.

### Migration workflow
```bash
# Apply all pending
alembic upgrade head

# After changing db/models.py
alembic revision --autogenerate -m "describe_change"
alembic upgrade head

# Check current state / history
alembic current
alembic history

# Roll back one
alembic downgrade -1
```

---

## Backend API

All routes registered in `api/main.py`. Protected routes require the
`access_token` httpOnly cookie (set automatically at login). Most routes also
require an active org context (`get_current_org`, re-derived from a live
`OrganizationMember` row on every request, never trusted from the JWT alone).

### Auth: `api/routes/auth.py`

```
POST /auth/register                 Create account + org (Turnstile-gated, promo code optional)
POST /auth/verify-email             Submit OTP from email
POST /auth/resend-verification      Re-send OTP
POST /auth/login                    Credentials login, sets cookies, or returns mfa_required
POST /auth/login/mfa                Submit TOTP (or backup code) during login challenge
POST /auth/logout                   Clear cookies, revoke session
POST /auth/refresh                  Silent token refresh (called by frontend proxy.ts)
GET  /auth/me                       Current client profile + orgs list
GET  /auth/orgs                     Orgs this client belongs to
POST /auth/switch-org               Switch active org, reissues cookies

POST /auth/forgot-password          Request password reset OTP (Turnstile-gated)
POST /auth/reset-password           Email + OTP + new password, revokes all sessions
POST /auth/change-password          Authenticated password change, revokes other sessions only

POST /auth/mfa/setup                Generate TOTP secret + QR URI
POST /auth/mfa/verify               Confirm TOTP code, enable MFA, get backup codes
POST /auth/mfa/disable              Disable MFA
POST /auth/mfa/nudge-dismiss        Dismiss the "enable MFA" dashboard banner

GET    /auth/sessions               List active sessions
DELETE /auth/sessions/{id}          Revoke one session
DELETE /auth/sessions               Revoke all (logout all devices)

POST /auth/delete-account           DPDP account deletion (confirmation="DELETE")
```

### Client / org config: `api/routes/clients.py`
```
GET   /clients/me                        Org's S3 + blocking + alert config (owner/admin)
PATCH /clients/me                        Update any org config field, re-tests S3 on save
POST  /clients/me/accept-blocking-tos    One-time acceptance gate before blocking is allowed
POST  /clients/me/onboarding/dismiss     Stop auto-opening the guided onboarding modal (owner/admin)
POST  /clients/me/onboarding/complete    Mark guided onboarding finished (owner/admin)
```

### Team & invites: `api/routes/org.py`
```
POST   /org                                   Create/join an org (general-purpose)
POST   /org/invite                            Invite a member (owner/admin, admin capped at viewer role)
GET    /org/invites                           List pending invites
POST   /org/invites/{id}/resend               Resend an invite email
DELETE /org/invites/{id}                      Cancel a pending invite
GET    /org/members                           List team members
PATCH  /org/members/{id}                      Change a member's role (owner only)
DELETE /org/members/{id}                      Remove a member (owner only)
POST   /org/members/{id}/transfer-ownership   Hand off ownership (target must already be admin)
GET    /org/invite/{token}                    Public: look up an invite by token
POST   /org/invite/{token}/accept             Public: accept (new account or existing)
```

### Verdicts: `api/routes/verdicts.py`
```
GET  /verdicts                    Paginated, multi-select severity + threat-type + date-range filters
GET  /verdicts/threat-types       Distinct threat_type values for the filter dropdown
GET  /verdicts/{id}               Full detail: agent scores, sample logs, org tier, ip_memory context
POST /verdicts/manual-block       Manually block an IP (creates a "manual" verdict + ip_memory row)
POST /verdicts/{id}/block         Enqueue WAF/Cloudflare block (paid tiers, owner/admin, ToS-gated)
POST /verdicts/{id}/unblock       Enqueue unblock (never tier-gated, by design)
```

### Dashboard: `api/routes/dashboard.py`
```
GET /dashboard/summary?days=7   Totals, by_severity, trend, top_ips, S3/scan status, cost_prevented
```

### IPs: `api/routes/ips.py`
```
GET  /ips                 Paginated ip_memory rows (sortable, filterable, blocked_only)
POST /ips/{ip}/unblock    Unblocks via that IP's latest blocked verdict
```

### Alerts: `api/routes/alerts.py`
```
GET  /alerts         Paginated delivery log (alerts_sent joined with the triggering verdict)
POST /alerts/test    Send a non-persisted test alert email (owner/admin)
```

### Settings: `api/routes/settings.py`
```
POST /settings/test-waf          Verify AWS WAF IP set access (Growth+)
POST /settings/test-cloudflare   Verify Cloudflare zone access (Growth+)
```

### Newsletter: `api/routes/newsletter.py`
```
POST /newsletter/subscribe   Public, rate limited, honeypot-guarded. Sends a double opt-in email.
                             Returns an identical response for an already-subscribed address.
POST /newsletter/confirm     Public, confirms the opt-in token and adds the contact in Resend
```

### Billing: `api/routes/billing.py`
```
GET  /billing/status                          Plan, period, open bills, payment history, billing details, refund eligibility (owner)
GET  /billing/banner                          Small subset for the dashboard banner (any member, viewers included)
PUT  /billing/details                         Billing legal name, address, GSTIN (owner)
POST /billing/checkout                        Stripe Checkout Session (pending live keys)
POST /billing/portal                          Stripe Customer Portal Session
POST /billing/webhook                         Stripe webhook (verify signature + update tier)

POST /billing/razorpay/create-order           Price a purchase server-side (initial, upgrade, bill, restore), create a Payment + Razorpay order
POST /billing/razorpay/verify-payment         Check the checkout.js HMAC, fetch the payment, apply it (idempotent)
POST /billing/razorpay/webhook                payment.captured / payment.failed / refund.processed (HMAC verified)

POST /billing/refund-eligibility              72h window from the first captured payment
POST /billing/refund                          Full refund of the payments inside that window, org drops to free
POST /billing/schedule-downgrade              Lower tier or annual to monthly, applied at the next bill
POST /billing/cancel                          Cancel at the end of the paid period
```

---

## Authentication — How It Works

**Two-token system, both httpOnly cookies:**

- **Access token**: 15-minute JWT. Validated on every protected request by
  `api/deps.py::get_current_client()`. `type: "access"` claim prevents a refresh
  token being used as an access token. Optionally carries an `org_id` claim, but
  `get_current_org()` always re-verifies that claim against a live
  `OrganizationMember` row; the JWT is never trusted alone for role/tenant checks.

- **Refresh token**: 7-day JWT. Stored as SHA-256 hash in `refresh_tokens` table.
  When the access token expires, the frontend's `apiFetch()` wrapper (`lib/api.ts`)
  automatically calls `/auth/refresh` and retries, the user never sees a session
  expiry unless the refresh token itself is invalid, in which case a
  `SessionExpiredModal` appears.

**Token rotation:** Each call to `/auth/refresh` revokes the old token and issues
a new pair. If a refresh token is stolen and used, the victim's next genuine refresh
attempt will fail (the token was revoked), alerting them that something is wrong.

**Password hashing:** SHA-256 pre-hash → bcrypt(rounds=12). Pre-hashing prevents
bcrypt's 72-byte truncation issue for long passwords.

**RBAC:** every org member has a role (`owner` / `admin` / `viewer`) via
`OrganizationMember`. `owner`: everything, including billing and member
management. `admin`: S3/blocking/alert config, invites (capped at inviting
viewers), block/unblock. `viewer`: read-only dashboard/verdicts/IPs, no
settings/billing/team/blocking access. Enforced with `Depends(require_role(...))`
in `api/deps.py`, never in the frontend alone.

**MFA (TOTP) flow:**
- Setup: `POST /auth/mfa/setup` returns an `otpauth://` URI. User scans with any
  authenticator app. `POST /auth/mfa/verify` confirms and enables MFA, returns
  10 backup codes.
- Login with MFA: `POST /auth/login` returns `{"mfa_required": true, "mfa_token": "..."}`.
  Frontend shows a TOTP prompt (or "use a backup code" option).
  `POST /auth/login/mfa` validates either and issues cookies.
- TOTP secret stored Fernet-encrypted in DB. Requires `TOTP_ENCRYPTION_KEY` env var.

**CAPTCHA:** Cloudflare Turnstile gates `/auth/register` and `/auth/forgot-password`.
`verify_turnstile_token()` fails closed: a blank `TURNSTILE_SECRET_KEY` means every
attempt is rejected. See "Running Locally" for the dummy test keys.

**Login lockout:** 5 failed attempts locks an email out for 15 minutes
(`clew:login_fail:{sha256(email)}` in Redis), separate from the general
per-request rate limiter. Lockout emails are only sent for accounts that
actually exist, so lockout timing can't be used to enumerate valid emails.

**Account deletion (item 40, DPDP):** `POST /auth/delete-account` soft-deletes
the `Client` (email anonymized immediately, login blocked on the very next
request since `deleted_at` is re-checked from the DB, not just the JWT). If the
client is an `owner` of any org, that whole `Organization` is soft-deleted too
(no ownership-transfer safety net beyond warning the user in the confirm modal
(`POST /org/members/{id}/transfer-ownership` exists for handing off ownership
*before* deleting, if that's what's wanted instead). A daily Beat task
hard-deletes anything soft-deleted more than 30 days ago.

---

## The Detection Engine

### Six active agents run in parallel, plus one passive

| Agent | Signal | Algorithm |
|---|---|---|
| `VolumeAgent` | DoS / floods | Isolation Forest on request rate |
| `TemporalAgent` | Bot timing, off-hours patterns | FFT + CUSUM |
| `AuthAgent` | Brute force, credential stuffing | Failed login rate analysis |
| `PayloadAgent` | SQLi, XSS, path traversal | Pattern matching |
| `SequenceAgent` | Endpoint enumeration | Sequence pattern analysis |
| `GeoIPAgent` | Geographic anomalies | Graph-based clustering + GeoLite2 ASN/City |
| `KnowledgeAgent` | Cross-session threat memory | Known signature matching, **passive**, emits no verdict of its own |

Docs (including older versions of this one) sometimes say "seven agents":
`KnowledgeAgent` doesn't produce a fusion input, so only 6 are "active."

### Orchestrator: `detection/engine/coordinator/meta_agent.py`

`MetaAgentOrchestrator` collects the 6 active agents' confidence scores and fuses them via:
1. Weighted average (per-agent weights tuned on training data)
2. XGBoost stacking model (trained on combined scores, online-fitted from the
   engine's own verdict history once ≥50 labeled verdicts exist; falls back to
   rule-based weighted vote during cold-start)
3. Conflict resolution rules

Output: `FusionVerdict`, 0–1 confidence score + explanation + per-agent findings
(all 6, including ones that didn't fire, each with a placeholder finding).

### Severity bands

| Confidence | Severity |
|---|---|
| ≥ 0.80 | critical |
| ≥ 0.60 | high |
| ≥ 0.40 | medium |
| < 0.40 | low |

### Calling the engine from Celery

```python
from engine.pipeline.run import run_pipeline

verdict_dict = run_pipeline(
    records=[{"timestamp": ..., "ip": ..., "method": ..., ...}],
    org_id="uuid-string",
    redis_client=redis_conn,
)
# Returns a dict ready to INSERT into the verdicts table, including
# agent_scores (full 6-agent breakdown) and sample_logs
```

### State persistence: LTM in Redis

The engine has two memory tiers:
- **STM** (Short-Term Memory): in-process sliding window, lives for one task
  invocation only
- **LTM** (Long-Term Memory): baseline rates, IAT reference pools, agent history,
  timezone/off-hours history, robust-estimator lock state, and `KnowledgeAgent`'s
  per-IP reputation history plus known-bad set, persisted to Redis key
  `clew:ltm:{org_id}` after every batch

`ProductSharedMemory` (subclasses `SharedMemory`) loads LTM from Redis on init
and calls `mem.flush()` to write back after each batch. Worker restarts and
redeployments do not lose detection context.

The Redis key's TTL is tier-aware (`LTM_TTL_DAYS` in `api/tiers.py`): the free
tier's learned state expires after 7 days of inactivity, matching its data
retention window. Every other tier uses the engine's default 30-day idle TTL.

**When adding a new LTM field, add it to both `_dump_ltm()` and `_load_ltm()`
in `product_memory.py` and write a round-trip test using a second, fresh
`ProductSharedMemory` instance.** Fields have been silently dropped from that
serialization twice, and the offline eval harness cannot catch it because it
reuses one in-process memory object and never round-trips through Redis.

### Known limitation

Pass B's per-IP focus pass needs ≥20 requests/IP/poll to trigger; thousands of
low-volume IPs can evade both passes. Pass C (cross-IP clustering, Pro and
Enterprise only) groups similar low-volume IPs, but it is alert only (no
auto-block, template explanation, `cluster:`-prefixed `source_key`) and has not
been validated on real distributed traffic.

### Import path setup

`detection/engine/pipeline/run.py` inserts `detection/` onto `sys.path` at import
time, so `from engine.xxx` and `from schemas.models` resolve correctly regardless
of Celery's working directory.

---

## Celery Pipeline

### Beat-scheduled tasks (`workers/beat.py`)

| Task | Schedule | Purpose |
|---|---|---|
| `poll_all_clients` | every 15 min | Fans out one `process_logs` per org with S3 configured (skips soft-deleted orgs). Free-tier orgs **are** scanned: the old expired-unpaid-trial exclusion was removed when Starter became permanently free |
| `send_trial_reminders` | daily 09:00 UTC | 5-day and 2-day trial-ending emails; reverts tier to `starter` on actual expiry. Only promo-code Growth trials exist |
| `purge_deleted_accounts` | daily 03:00 UTC | Hard-deletes orgs/clients soft-deleted 30+ days ago, plus `processed_webhook_events` rows older than 30 days |
| `purge_expired_data` | daily 04:00 UTC | Tiered retention purge across `alerts_sent`, `verdicts`, `scan_runs`, `ip_memory`, per `RETENTION_DAYS`. Enterprise is skipped entirely |
| `reset_monthly_counters` | 1st of month 00:00 UTC | Zeroes `monthly_requests_processed` and clears both quota-email flags |
| `billing_cycle` | daily 19:00 UTC | Bill engine. 19:00 UTC is 00:30 IST, just after the IST midnight the billing dates (the 1st, 17th, 20th) are evaluated at |
| `metrics_snapshot` | daily 19:30 UTC | Business metrics snapshot for the ops panel, 30 minutes after `billing_cycle` |
| `reconcile_payments` | daily 19:45 UTC | Compares Razorpay payments with local rows and reports differences to the ops panel. Applies nothing |

### `process_logs`: the main task, one per org per poll

1. Acquire a per-org Redis lock (`clew:lock:process:{org_id}`, 20-min TTL), skips
   if already running, so Beat firing again during a large backlog can't double-process
2. Load org from DB; skip if no S3 config
3. On first-ever connection: sanity-check the configured log format against a
   sample of the most recent object, and pull the last 7 days of history
   (otherwise, only objects newer than `last_processed_key`)
4. Parse + normalize log lines into 500-record batches, each line tagged with a
   `source_key` (`{s3_key}:{line_offset}`) for dedup
5. **Pass A**: mixed-IP window batches through the full engine, writes LTM
6. **Pass B**: a restricted per-IP focus pass for IPs with ≥20 requests this
   poll (catches attackers whose traffic would otherwise be diluted across
   window boundaries); reads LTM, never writes it
7. Persist `verdicts` (or a `scan_runs` row if the batch was clean) + upsert `ip_memory`,
   skipping any row whose `source_key` already exists (idempotent re-processing)
8. Advance `last_processed_key` only after a successful commit
9. Enqueue `send_alerts` for the org's threshold, `push_block` for Growth/Pro high-confidence verdicts
10. On the first scan that processes at least one record, send the `org_activated` analytics event (once per org, Redis-deduplicated, never fails the scan)

The logs heartbeat (`HEARTBEAT_URL`) is pinged by `poll_all_clients` after it dispatches, not by `process_logs`.

**`send_alerts`**: Resend email, respects `alert_severity_threshold`. Deduplicates via
`alerts_sent`. Skipped entirely for the free tier (gated on `MANUAL_BLOCK_TIERS`).

**`push_blocks`**: checks confidence >= 0.75, then calls `blocking/aws_waf.py` and/or
`blocking/cloudflare.py` independently (one can succeed while the other fails), using a
cross-account session from `aws_session_for_org()` for the WAF call. Tier is checked by
the two callers rather than inside the task, because they use different tier sets:
`process_logs.py` checks `AUTO_BLOCK_TIERS` for the unattended path, `verdicts.py` checks
the wider `MANUAL_BLOCK_TIERS` for the dashboard buttons.

> **Known gap:** the automatic path does **not** currently check
> `blocking_tos_accepted_at`, and there is no per-org on/off switch for automatic
> blocking. Only the two manual routes enforce the agreement. See TODO2.md,
> "Blocking", for the fix.

---

## Frontend

### Design system

No component library. All styling via CSS variables in `globals.css`. The
aesthetic is monospace and terminal-inspired — no rounded corners, no gradients.
The full design system is documented in `DESIGN_SYSTEM.md`. Always read that
before touching any CSS.

Key variables:
```css
--color-bg         /* page background */
--color-surface    /* card/panel background */
--color-border     /* all borders */
--color-text       /* primary text */
--color-text-muted /* secondary text */
--color-critical / --color-high / --color-medium / --color-low
--font-brand       /* Courier Prime — used for "Clew" wordmark only */
--font-sans        /* Geist — body text */
--font-mono        /* Geist Mono — code + data */
```

### Pages

| Route | Type | What it shows |
|---|---|---|
| `/` | Server | Marketing homepage: Hero, CostCalculator, HowItWorks, AgentsSection, Pricing, Footer |
| `/pricing` | Server | Standalone pricing comparison page |
| `/docs` | Client | Public documentation, 14 sections, reuses `LegalLayout`'s scroll-spy TOC |
| `/legal/*` | Client | terms, privacy, dpa, subscription-agreement, refund-policy (scroll-spy TOC) |
| `/login` | Client | Email + password |
| `/register` | Client | Email + password + company name, Turnstile CAPTCHA, promo code, ToS checkbox. Reads `?plan=` to carry a chosen paid tier into checkout after verification |
| `/verify-email` | Client | 6-digit OTP input |
| `/forgot-password` | Client | Email field + Turnstile (anti-enumeration: always shows "if registered, check email") |
| `/reset-password` | Client | Email + OTP + new password |
| `/accept-invite` | Client | Reads `?token=`, handles new-account / existing-account / expired / already-used |
| `/newsletter/confirm` | Client | Double opt-in confirmation landing page |
| `/dashboard` | Client | Stats grid, trend chart, top IPs, scanning banner, empty states, guided-onboarding entry point |
| `/dashboard/alerts` | Client | "Verdicts" + "Notifications" tabs (delivery log, test-alert button) |
| `/dashboard/ips` | Client | "All IPs" + "Blocked" tabs, manual block form |
| `/dashboard/verdicts/[id]` | Client | Agent-score table, raw log sample, AI analysis (tier-gated), block/unblock |
| `/dashboard/settings` | Client | AWS access (IAM role), WAF/Cloudflare, MFA, team, billing, change password, delete account |

Guided onboarding is a modal (`OnboardingModal.tsx`) that auto-opens on first
dashboard load for owners and admins, is dismissible, and is re-openable from
`GuidedOnboardingButton.tsx` on the empty dashboard and from Settings. Its
state is per organization (`onboarding_completed_at` / `onboarding_dismissed_at`),
not per user, and it is exposed on `GET /dashboard/summary` so viewers (who
cannot call `/clients/me`) still render correctly.

### Auth middleware: `frontend/src/proxy.ts`

This is Next.js 16's renamed `middleware.ts`, same edge-middleware mechanism,
new filename. Runs at the Edge (Web Crypto API, no Node.js) on every request
before React:
- `/dashboard/*`: verify `access_token` JWT with `jose`. If expired, call
  `POST /auth/refresh` silently. If refresh fails, redirect to `/login?next=<path>`.
- Auth pages: if already authenticated, redirect to `/dashboard`.

### Data fetching pattern

Most dashboard pages use `apiFetch()` from `lib/api.ts` (not raw `fetch`), it
sends `{ credentials: "include" }`, and on a 401 silently calls `/auth/refresh`
and retries once before giving up and showing `SessionExpiredModal`. Pre-auth
pages and the Navbar's is-logged-in probe deliberately use plain `fetch`
instead, a 401 there just means "not logged in," not "session expired."

### Cookies

Auth cookies are host-only (no `Domain` attribute) in every environment. The
browser calls the API same-origin at `/api/*` on both `www` and `dashboard`, so
the host that serves the page is also the host that sets and receives the
cookies. `COOKIE_DOMAIN` stays blank. `LEGACY_COOKIE_DOMAIN` exists only to
delete the old `.clewsec.com` cookies during the transition.

---

## Blocking Integrations

Two separate tier gates, defined in `api/tiers.py`:

- `MANUAL_BLOCK_TIERS` (`starter`, `growth`, `pro`, `enterprise`): the dashboard
  block button. Basic and up can block an IP by hand.
- `AUTO_BLOCK_TIERS` (`growth`, `pro`, `enterprise`): the unattended,
  pipeline-triggered block. Basic does **not** get this.

The free Starter tier gets no blocking at all. Blocking is gated behind a
one-time Blocking Subscription Agreement acceptance
(`POST /clients/me/accept-blocking-tos`). Unblocking is never tier-gated and
never agreement-gated, by design, so a downgraded org can always remove blocks
it created.

**AWS WAF v2** (`blocking/aws_waf.py`): adds/removes IPs from a customer-owned
WAF IP set. The customer creates the IP set and stores its identifier in
Settings. Access goes through the same cross-account IAM role used for S3
ingestion (`aws_session_for_org()`), with `wafv2:GetIPSet` and
`wafv2:UpdateIPSet` added to that role's permissions policy. One role, two
capability sets, no second trust relationship. `UpdateIPSet` is a
read-modify-write against a `LockToken` from `GetIPSet`, which is why both
permissions are required.

**Cloudflare** (`blocking/cloudflare.py`): creates/deletes block rules on the
customer's zone using the Cloudflare API. `cloudflare_zone_id` and
`cloudflare_token` are stored per-org in `organizations`, with the token
Fernet-encrypted at rest.

Both can be configured simultaneously, high-confidence threats are blocked on
all configured integrations, and each tracks its own `*_blocked` / `*_block_error`
state independently in `ip_memory` (one can fail while the other succeeds).

> **Known gap:** the automatic path does not check `blocking_tos_accepted_at`,
> and there is no per-org toggle to turn automatic blocking on or off. See
> TODO2.md, "Blocking".

---

## Billing

Razorpay is the only live provider. Orgs are billed in USD by default and in
INR when the billing country is India. The Stripe code is kept but unused (it
is subscription based and would need adapting to the bill-then-pay rules).

**Razorpay flow (Orders, bill then pay; no Razorpay subscriptions or Plans):**
1. The customer picks a plan, a bill to pay, an upgrade or a restore. The
   frontend calls `POST /billing/razorpay/create-order` with the purpose and
   plan only. The server computes the amount from `PLAN_PRICES`
   (`api/tiers.py`, keyed by currency, tier and period) and the rules in `api/billing_rules.py`, writes a
   `payments` row (`status='created'`) and creates the Razorpay order.
2. Razorpay Checkout opens client-side. On success the frontend calls
   `POST /billing/razorpay/verify-payment` with the order id, payment id and
   signature. The server checks the HMAC-SHA256 of `order_id|payment_id`,
   fetches the payment from Razorpay, requires status `captured` and the
   stored amount, then calls `apply_captured_payment`.
3. Razorpay also sends `payment.captured`, `payment.failed` and
   `refund.processed` to `POST /billing/razorpay/webhook` (HMAC verified
   against `RAZORPAY_WEBHOOK_SECRET`, replay guarded by
   `processed_webhook_events`). `payment.captured` calls the same
   `apply_captured_payment`, which is row-locked and idempotent, so the
   browser callback and the webhook together credit a payment exactly once.
4. `apply_captured_payment` (`api/billing_payments.py`) is the only place a
   payment changes an org: plan purchase, upgrade, bill payment or restore.
   The Blocking Agreement and GSTIN are recorded here, not before the charge.
   A failed or abandoned checkout changes nothing on the org.
5. The daily `billing_cycle` task (`workers/tasks/billing_cycle.py`) issues
   bills, applies scheduled downgrades, cancels at period end and downgrades
   orgs whose bill is unpaid past its cancel date.
6. Refund: `POST /billing/refund` refunds every payment captured within 72
   hours of the first one, in full, and drops the org to free.
   `POST /billing/refund-eligibility` reports the window. `POST /billing/cancel`
   and `POST /billing/schedule-downgrade` only record intent for the next bill.

**Stripe flow (code complete, not live):**
1. User clicks Upgrade → `POST /billing/checkout` → FastAPI creates a Stripe
   Checkout Session → redirects to Stripe's hosted payment page
2. Stripe sends `checkout.session.completed` to `POST /billing/webhook`
3. Webhook verifies the Stripe signature, sets `org.tier` + subscription IDs

**Trials & promo codes:** every signup gets a trial (7 days self-serve, 30
days with a valid promo code from the `promo_codes` table). A daily Beat task
reverts the tier to `starter` once an unpaid trial's `trial_ends_at` passes.

**Currency:** auto-detected from browser timezone (Kolkata/India → INR, else USD).
Toggle available on the pricing page.

**What to do when Stripe keys arrive:** see the "Adding Stripe Later" section
further down this file.

---

## Common Development Tasks

### Add a new API endpoint

1. Add a function to an existing file in `api/routes/` (or create a new file)
2. Use `router = APIRouter()` at the top of new files
3. Wire new files into `api/main.py` with `app.include_router(router)`
4. Protected routes: add `client: Client = Depends(get_current_client)` for
   login-only checks, or `current_org: CurrentOrg = Depends(get_current_org)`
   for org-scoped routes (the common case), add
   `Depends(require_role("owner", "admin"))` on top of that if the route
   needs an RBAC floor
5. DB access: add `db: Session = Depends(get_db)`

### Add a new DB column

1. Edit `db/models.py`
2. `alembic revision --autogenerate -m "add_column_name"`
3. Review the generated file in `db/migrations/versions/`
4. `alembic upgrade head`

### Test an endpoint

FastAPI auto-docs at `http://localhost:8000/docs`, or curl:
```bash
# Login and save cookies
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"pass123"}' \
  -c cookies.txt

# Call protected endpoint
curl http://localhost:8000/auth/me -b cookies.txt
```

### Add a new frontend page

1. Create `frontend/src/app/<route>/page.tsx`
2. `/dashboard/*` routes are automatically protected by middleware — no extra config
3. For public pages with SEO: export `metadata` from the page file (if server
   component) or a co-located `layout.tsx` (if client component)

### Run the integration tests

```bash
source .venv/bin/activate
python -m pytest detection/engine/tests/ -v
```

### Inspect Redis

```bash
redis-cli
> KEYS clew:*
> GET clew:ltm:<org_id>
```

### Connect to DB

```bash
psql postgresql://clew:password@localhost:5432/clew
\dt              # list tables
\d organizations # describe a table
```

### Check Celery task logs (production)

```bash
pm2 logs clew-worker --lines 200
pm2 logs clew-beat --lines 50
```

### Restart a process (production)

```bash
pm2 restart clew-api
pm2 restart all
```

---

## Environment Variables

All variables are documented in `.env.example`. The four that must be set for
anything to work:

| Variable | Description |
|---|---|
| `DATABASE_URL` | `postgresql://user:password@host:port/dbname` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `JWT_SECRET` | 64-char hex, shared between backend `.env` and `frontend/.env.local` |
| `TOTP_ENCRYPTION_KEY` | Fernet key, generated with `Fernet.generate_key()` |

Also required for register/forgot-password to work at all:
`TURNSTILE_SECRET_KEY` (backend) + `NEXT_PUBLIC_TURNSTILE_SITE_KEY` (frontend):
see "Running Locally" for Cloudflare's dummy test keys.

Set `LOG_EMAILS=1` locally to print all sent emails to terminal instead of
sending via Resend. Do not set this in production.

`RESEND_API_KEY`: get from [resend.com](https://resend.com) dashboard → API Keys.
For S3/WAF, use `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_DEFAULT_REGION`.
For Razorpay billing, `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` /
`RAZORPAY_WEBHOOK_SECRET` (no Plan IDs are needed, see "Adding Razorpay Later").

---

## What Is Not Yet Active

- **Stripe billing**: not used. The code is kept and the DB columns exist, but
  the decision is to stay on Razorpay only (it handles USD and INR). Adding
  Stripe later means adapting it to the bill-then-pay rules; see "Adding Stripe
  Later".
- **Razorpay is not live yet**: the Orders integration is code complete and
  tested against a fake client, but the live `RAZORPAY_*` env vars are blank,
  pending bank and KYC approval. Every code path degrades to a clean 503 with
  blank keys. Test-mode keys work from `.env.local`. Live mode also needs
  auto-capture switched on in the Razorpay dashboard and the webhook URL
  pointed at `/billing/razorpay/webhook`.
- **Automatic blocking has no on/off switch and does not check the blocking
  agreement.** Configuring a WAF IP set on Growth or above turns unattended
  blocking on implicitly. See TODO2.md, "Blocking".
- **Pro's "lower detection confidence threshold" and "custom thresholds"** are
  built (Phase 8) and gated to Pro and Enterprise by `CUSTOM_THRESHOLD_TIERS`
  in `api/tiers.py`. Settings live in `Client.detection_config`, validated by
  `api/detection_config.py` (attack 0.40 to 0.90, default 0.60; block 0.50 to
  0.95, default 0.75; per-agent minimums; up to 20 endpoint minimums). The
  block threshold applies to the automatic path only; manual blocks keep 0.75.
  Growth and above can also turn on `auto_block_dry_run`, which records
  `Verdict.would_have_blocked_at` instead of pushing a block
  (`GET /verdicts/would-have-blocked`). The LLM only writes the explanation
  after the rules decide (`LLM_ENABLED` is the kill switch, `LLM_MODEL`
  defaults to `openai/gpt-oss-20b`). `ABUSEIPDB_API_KEY` is optional; the code
  caps lookups at 900 a day against the free plan's 1000. When set, the
  orchestrator looks up the busiest IP of a batch that an agent already
  flagged, and a hit adds 0.08 to the fused confidence (`_REPUTATION_BOOST` in
  `meta_agent.py`). It never creates a detection alone. A circuit breaker stops
  calls after 3 consecutive failures. Offline CICIDS runs with stubbed
  reputation showed no regression (F1 0.8500 with none, 0.8502 with attackers
  flagged), so the gain is unproven until real traffic.
- **Sentry / exception tracking, a public status page, an internal ops panel,
  and a staging environment**: all post-MVP. None block onboarding a first real
  client; revisit when there is an actual client or audience to justify them.
- **Webhook/Slack/PagerDuty alert channels and a public customer-facing API +
  API keys**: post-MVP, no customer has asked for either yet.
- **Database backups and uptime monitoring**: the runbook exists in this file
  but the cron job and monitors are not set up yet.

For the full forward-looking list, see `TODO2.md`. `TODO.md` holds the build
history and the Razorpay go-live checklist.

---

## Testing and Deployment

This is a linear walkthrough for deploying to production. Do every step in order.
When it says "on your laptop" it means a terminal on your local machine, not the SSH session.

---

### What you will end up with

- `https://www.clewsec.com`: Next.js marketing site (`clewsec.com` redirects here)
- `https://dashboard.clewsec.com`: the app (same Next.js process)
- `https://api.clewsec.com`: FastAPI backend (webhooks and external API; the browser uses `/api` on the two hosts above)
- Four PM2-managed background processes: `clew-api`, `clew-frontend`, `clew-worker`, `clew-beat`
- PostgreSQL + Redis, both localhost-only

---

### Phase 1 — AWS Setup

#### 1.1 Create an IAM user for Clew

Your server needs to call WAF to block IPs. Create a dedicated machine user `clew-server`.

**Step A — Create the WAF policy:**
1. IAM → Policies → Create policy → JSON tab → paste:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": ["wafv2:GetIPSet", "wafv2:UpdateIPSet"],
       "Resource": "*"
     }]
   }
   ```
2. Name it `ClewWAFBlockingPolicy` → Create policy

**Step B — Create the user:**
1. IAM → Users → Create user → Username: `clew-server`
2. Leave console access unticked (machine user, not a person)
3. Attach policies directly → search `ClewWAFBlockingPolicy` → tick it → Create user

**Get access keys:**
1. Click the new user → Security credentials tab → Create access key
2. Use case: "Application running outside AWS"
3. Copy both values into a password manager immediately — the secret is shown once only
4. These go in `.env` as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`

---

#### 1.2 Set up Resend for outbound email

1. [resend.com](https://resend.com) → Domains → Add Domain → `email.clewsec.com`
2. Add the DNS records Resend shows you (DKIM TXT, SPF TXT, DMARC TXT) in your registrar
3. Verify the domain in Resend
4. API Keys → Create API Key → `clew-production` → Full access → copy the key
5. Add to `.env` as `RESEND_API_KEY`

---

#### 1.3 Set up Cloudflare Turnstile

One-time setup, same as 1.1/1.2 above. Registration and forgot-password fail
closed without this, there's no way to skip it in production.

1. [dash.cloudflare.com](https://dash.cloudflare.com) → Turnstile → **Add widget manually**
   (not "Set up with Spin", that's Cloudflare's own AI agent offering to
   auto-wire the integration into your codebase itself; the integration is
   already built here, you only need the keys)
2. Domain: `clewsec.com` (and `www.clewsec.com` if you want both covered)
3. Widget mode: Managed (recommended default)
4. Copy the **Site Key** → add to `frontend/.env.local` as `NEXT_PUBLIC_TURNSTILE_SITE_KEY`
5. Copy the **Secret Key** → add to `.env` as `TURNSTILE_SECRET_KEY`

---

### Phase 2 — EC2 Server

#### 2.1 Launch the instance

AWS Console → EC2 → Launch instances:
- **Name:** `clew-production`
- **AMI:** Ubuntu Server 24.04 LTS (Canonical)
- **Instance type:** `t3.small` (2 vCPU, 2 GB RAM, ~$15/month)
- **Key pair:** Create new → `clew-key` → RSA → .pem format
  ```bash
  # On your laptop after download:
  mv ~/Downloads/clew-key.pem ~/.ssh/clew-key.pem
  chmod 400 ~/.ssh/clew-key.pem
  ```
- **Security group inbound rules:**

  | Port | Source |
  |---|---|
  | 22 SSH | My IP |
  | 80 HTTP | Anywhere |
  | 443 HTTPS | Anywhere |

- **Storage:** 20 GB gp3

#### 2.2 Elastic IP (permanent IP address)

EC2 → Elastic IPs → Allocate → Actions → Associate → select `clew-production`.
Write down the IP — it goes in every SSH command and DNS record.

#### 2.3 DNS

In your registrar, add:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | @ | Elastic IP | 300 |
| A | api | Elastic IP | 300 |

---

### Phase 3 — Server Setup

#### 3.1 SSH in

```bash
ssh -i ~/.ssh/clew-key.pem ubuntu@YOUR_ELASTIC_IP
```

First connection: type `yes` to accept the host key.

#### 3.2 System packages

```bash
sudo apt update && sudo apt upgrade -y

# Python 3.12
sudo apt install -y python3.12-venv python3.12-dev build-essential

# Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# PostgreSQL
sudo apt install -y postgresql postgresql-contrib

# Redis
sudo apt install -y redis-server

# Nginx
sudo apt install -y nginx

# Certbot
sudo apt install -y certbot python3-certbot-nginx

# PM2
sudo npm install -g pm2

# Git
sudo apt install -y git
```

#### 3.3 Create the PostgreSQL database

```bash
sudo -u postgres psql << 'EOF'
CREATE USER clew WITH PASSWORD 'REPLACE_WITH_STRONG_PASSWORD';
CREATE DATABASE clew OWNER clew;
GRANT ALL PRIVILEGES ON DATABASE clew TO clew;
EOF
```

Use 20+ random characters for the password. Save it — it goes in `DATABASE_URL`.
Postgres listens on localhost only. Never open port 5432 in your security group.

#### 3.4 Lock Redis to localhost

```bash
sudo nano /etc/redis/redis.conf
# Ensure this line is present and NOT commented out:
# bind 127.0.0.1 ::1

sudo systemctl restart redis-server
sudo systemctl enable redis-server
```

---

### Phase 4 — Deploy the Code

#### 4.1 Clone the repository

```bash
cd /home/ubuntu
git clone https://github.com/Aza3l01/abuse.git
cd abuse
```

#### 4.2 Download GeoIP databases

```bash
MAXMIND_LICENSE_KEY=YOUR_MAXMIND_LICENSE_KEY ./scripts/download_geoip.sh
```

Expected output shows both `GeoLite2-ASN.mmdb` (12 MB) and `GeoLite2-City.mmdb` (63 MB) written to `detection/datasets/`.

**Monthly auto-update (add after server is stable):**
```bash
crontab -e
# Add this line:
0 3 1 * * cd /home/ubuntu/abuse && MAXMIND_LICENSE_KEY=$(grep MAXMIND_LICENSE_KEY .env | cut -d= -f2) ./scripts/download_geoip.sh >> /var/log/geoip_update.log 2>&1
```

#### 4.3 Python virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Takes about 2 minutes. Run `source .venv/bin/activate` every time you SSH in and need to run Python manually.

#### 4.4 Create the backend .env file

```bash
cp .env.example .env
chmod 600 /home/ubuntu/abuse/.env
nano /home/ubuntu/abuse/.env
```

Fill in every value. Generate the two secrets on your laptop:
```bash
# JWT secret (64 hex characters)
openssl rand -hex 64

# TOTP Fernet key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Key values to fill in:
- `DATABASE_URL` — use the password from step 3.3
- `JWT_SECRET` — paste the openssl output
- `TOTP_ENCRYPTION_KEY` — paste the Fernet key
- `DASHBOARD_URL=https://dashboard.clewsec.com`
- `HOME_URL=https://www.clewsec.com`
- `COOKIE_DOMAIN`: leave blank (host-only cookies)
- `TURNSTILE_SECRET_KEY`: from step 1.3
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — from step 1.1
- `RESEND_API_KEY` — from step 1.2
- `MAXMIND_LICENSE_KEY` — your MaxMind key

#### 4.5 Run database migrations

```bash
cd /home/ubuntu/abuse
source .venv/bin/activate
alembic upgrade head
```

Expected:
```
INFO  [alembic.runtime.migration] Running upgrade  -> c957d12130b9, initial schema
INFO  [alembic.runtime.migration] Running upgrade c957d12130b9 -> b4e8f2a1c953, add stripe billing columns
INFO  [alembic.runtime.migration] Running upgrade b4e8f2a1c953 -> e3c1a7f920d4, add mfa backup codes
```

#### 4.6 Create the frontend .env.local file

```bash
cat > /home/ubuntu/abuse/frontend/.env.local << 'EOF'
NEXT_PUBLIC_API_URL=/api
NEXT_PUBLIC_SITE_URL=https://www.clewsec.com
NEXT_PUBLIC_DASHBOARD_URL=https://dashboard.clewsec.com
DASHBOARD_HOST=dashboard.clewsec.com
HOME_URL=https://www.clewsec.com
API_INTERNAL_URL=http://127.0.0.1:8000
JWT_SECRET=PASTE_SAME_JWT_SECRET_AS_BACKEND_ENV
NEXT_PUBLIC_TURNSTILE_SITE_KEY=PASTE_SITE_KEY_FROM_STEP_1.3
EOF
```

`JWT_SECRET` must be identical to the value in `/home/ubuntu/abuse/.env`.

#### 4.7 Build the frontend

```bash
cd /home/ubuntu/abuse/frontend
npm install
npm run build
```

Takes 1–2 minutes. Any error here is almost always a missing env var.

#### 4.8 Monitoring setup

Do this once the environment above is live and reachable over HTTPS.

**Layer 1 (HTTP uptime, Better Stack):**
1. Better Stack → Uptime → Monitors → Create monitor → HTTP(s)
2. URL: `https://api.clewsec.com/health`
3. Check every 5 minutes or faster
4. Add your email as an alert contact

**Layer 2 (Beat task heartbeats, Better Stack):**
1. Better Stack → Uptime → Heartbeats → Create heartbeat
2. Logs heartbeat: period 15 minutes, grace 5 to 10 minutes. Copy its URL into `HEARTBEAT_URL` in `/home/ubuntu/abuse/.env`
3. Billing heartbeat (once there is a paying customer): period 1 day, grace 2 hours. Copy its URL into `BILLING_HEARTBEAT_URL`
4. `pm2 restart` the Beat and worker processes so the new env vars are picked up

`poll_all_clients` pings `HEARTBEAT_URL` after every run, even when no org is configured. The `billing_cycle` task pings `BILLING_HEARTBEAT_URL` on a clean run and `/fail` when any org errored or the run crashed. Both are no-ops when the variable is blank, so leave them blank in any non-production `.env`.

Exceptions: the API (`CorrelationIdMiddleware`), Celery task failures and the frontend report to PostHog error tracking when `POSTHOG_API_KEY` and `NEXT_PUBLIC_POSTHOG_KEY` are set. Sentry stays cut.

---

### Phase 5 — Nginx

The committed config is `docker/nginx.conf`. Copy it rather than hand-writing a second copy:

```bash
sudo cp /home/ubuntu/abuse/docker/nginx.conf /etc/nginx/sites-available/clew
```

It defines four hosts: `clewsec.com` (301 to `www`), `www.clewsec.com`
(Next.js), `dashboard.clewsec.com` (Next.js, `noindex`, `robots.txt` disallows
all) and `api.clewsec.com` (FastAPI). `www` and `dashboard` each have a
`location /api/` that strips the prefix and proxies to FastAPI on `:8000` with
the forwarded headers. Keep that in nginx: a Next.js rewrite would hide the
client IP from the rate limiter.

```bash
sudo ln -s /etc/nginx/sites-available/clew /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t    # must say "syntax is ok"
sudo systemctl reload nginx
```

---

### Phase 6 — HTTPS

DNS must be pointing at your server first:
```bash
ping clewsec.com             # must show YOUR Elastic IP
ping www.clewsec.com         # must show YOUR Elastic IP
ping dashboard.clewsec.com   # must show YOUR Elastic IP
ping api.clewsec.com         # must show YOUR Elastic IP
```

```bash
sudo certbot --nginx -d clewsec.com -d www.clewsec.com -d dashboard.clewsec.com -d api.clewsec.com
sudo certbot renew --dry-run    # verify auto-renewal works
```

---

### Phase 7 — PM2

#### 7.1 Copy the committed ecosystem.config.js

The process config is already committed at `docker/ecosystem.config.js`, copy it to the repo root on the server rather than hand-writing a second, divergent copy:

```bash
cp /home/ubuntu/abuse/docker/ecosystem.config.js /home/ubuntu/abuse/ecosystem.config.js
nano /home/ubuntu/abuse/ecosystem.config.js
```

Review the paths inside it (`cwd`, `interpreter`, `script`, `env_file`) match your deploy path (`/home/ubuntu/abuse`) before starting it:

```js
module.exports = {
  apps: [
    {
      name:        'clew-api',
      cwd:         '/home/ubuntu/abuse',
      interpreter: '/home/ubuntu/abuse/.venv/bin/python3',
      script:      '/home/ubuntu/abuse/.venv/bin/uvicorn',
      args:        'api.main:app --host 127.0.0.1 --port 8000 --workers 2',
      env_file:    '/home/ubuntu/abuse/.env',
    },
    {
      name:   'clew-frontend',
      cwd:    '/home/ubuntu/abuse/frontend',
      script: 'node_modules/.bin/next',
      args:   'start --port 3000',
      env: {
        NODE_ENV:                  'production',
        NEXT_PUBLIC_API_URL:       '/api',
        NEXT_PUBLIC_SITE_URL:      'https://www.clewsec.com',
        NEXT_PUBLIC_DASHBOARD_URL: 'https://dashboard.clewsec.com',
        DASHBOARD_HOST:            'dashboard.clewsec.com',
        HOME_URL:                  'https://www.clewsec.com',
        API_INTERNAL_URL:          'http://127.0.0.1:8000',
      },
    },
    {
      name:        'clew-worker',
      cwd:         '/home/ubuntu/abuse',
      interpreter: '/home/ubuntu/abuse/.venv/bin/python',
      script:      '/home/ubuntu/abuse/.venv/bin/celery',
      args:        '-A workers.celery_app worker --loglevel=info --concurrency=4',
      env_file:    '/home/ubuntu/abuse/.env',
    },
    {
      // IMPORTANT: run exactly ONE instance of clew-beat.
      // Two instances = every task fires twice.
      name:        'clew-beat',
      cwd:         '/home/ubuntu/abuse',
      interpreter: '/home/ubuntu/abuse/.venv/bin/python',
      script:      '/home/ubuntu/abuse/.venv/bin/celery',
      args:        '-A workers.celery_app beat --loglevel=info',
      env_file:    '/home/ubuntu/abuse/.env',
    },
  ],
};
```

#### 7.2 Start and register

```bash
cd /home/ubuntu/abuse
pm2 start ecosystem.config.js
pm2 save
pm2 startup    # copy and run the sudo command it prints
```

#### 7.3 Verify

```bash
pm2 status
# All four rows should show "online"
```

If any show `errored`:
```bash
pm2 logs clew-api --lines 50
pm2 logs clew-worker --lines 50
```

---

### Phase 8 — Firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Do NOT open 5432 (Postgres) or 6379 (Redis).

---

### Phase 9 — Verification Checklist

```bash
# API health (bypasses Nginx)
curl http://localhost:8000/health
# Expected: {"status":"ok"}

# Frontend up (bypasses Nginx)
curl -s http://localhost:3000 | head -5

# Redis alive
redis-cli ping
# Expected: PONG

# Migrations current
cd /home/ubuntu/abuse && source .venv/bin/activate && alembic current
# Expected: the same revision as `alembic heads` in the checked-out code, marked (head)

# All processes running
pm2 status
```

Browser checklist:

| URL | Expected |
|---|---|
| `https://www.clewsec.com` | Marketing homepage, padlock visible |
| `https://api.clewsec.com/health` | `{"status":"ok"}` |
| `https://clewsec.com` | 301 to `https://www.clewsec.com` |
| `http://www.clewsec.com` | Redirects to https:// |
| `https://dashboard.clewsec.com` | Redirects to `/login` when signed out |
| `https://dashboard.clewsec.com/register` | Registration form loads |

---

### Day-to-Day Commands

#### Pushing Code Updates

```bash
# SSH in:
ssh -i ~/.ssh/clew-key.pem ubuntu@YOUR_ELASTIC_IP

cd /home/ubuntu/abuse
git pull

# If requirements.txt changed:
source .venv/bin/activate && pip install -r requirements.txt

# If a migration was added:
source .venv/bin/activate && alembic upgrade head

# If frontend changed:
cd frontend && npm run build && cd ..

# Refresh GeoIP databases manually (monthly cron handles this normally):
MAXMIND_LICENSE_KEY=$(grep MAXMIND_LICENSE_KEY .env | cut -d= -f2) ./scripts/download_geoip.sh

# Restart what changed:
pm2 restart clew-api               # API or worker code
pm2 restart clew-frontend          # frontend (after npm run build)
pm2 restart clew-worker clew-beat  # Celery tasks

# When in doubt:
pm2 restart all
```

#### Database Backups

PostgreSQL runs on a single EC2 instance with no managed backup, so a nightly
`pg_dump` to S3 is the MVP backup strategy. Two scripts do the work:
`scripts/backup_postgres.sh` (dump, gzip, check, upload; exits non-zero on any failure) and
`scripts/restore_postgres.sh` (restore into a new, named throwaway database, never the live one).
Neither script contains a secret. Both read `DATABASE_URL` from the environment or the repo `.env`.

**Set up the backup bucket (once):**
1. S3 → Create bucket → `clew-db-backups`, Block all public access on, default encryption on
2. Add a lifecycle rule on the bucket that expires objects 30 days after creation. This is the only thing that ever deletes a backup
3. Give the `clew-server` IAM user (step 1.1) one extra statement, scoped to the backup bucket, that is **write-only**: `s3:PutObject` and nothing else. No `s3:DeleteObject`, no `s3:GetObject`, no `s3:ListBucket`, so a compromised server cannot wipe or read the backups

```json
{
  "Effect": "Allow",
  "Action": "s3:PutObject",
  "Resource": "arn:aws:s3:::clew-db-backups/db-backups/*"
}
```

4. Reading backups back needs a separate identity that is not on the server (your own IAM user or SSO profile with `s3:GetObject` and `s3:ListBucket` on this bucket)

**Server settings.** The server needs the `postgresql-client` tools and the AWS CLI v2 on `PATH`. Add one line to `.env`:
```bash
BACKUP_S3_BUCKET=clew-db-backups
```
`BACKUP_S3_PREFIX` is optional (default `db-backups`). The script reuses `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_DEFAULT_REGION` from `.env` (the `clew-server` user), so cron needs no extra credentials. Objects are named `db-backups/clew_YYYYMMDDTHHMMSSZ.sql.gz` (UTC).

**Add the nightly backup to crontab** (no password on the command line):
```bash
chmod +x scripts/backup_postgres.sh scripts/restore_postgres.sh
crontab -e
# Add this line:
0 2 * * * cd /home/ubuntu/abuse && ./scripts/backup_postgres.sh >> /home/ubuntu/clew_backup.log 2>&1
```
Run it once by hand first (`./scripts/backup_postgres.sh`); it prints the S3 key it wrote. A failed run ends with an `ERROR:` line in `clew_backup.log` and a non-zero exit code. Check the log after the first few nights, and glance at it weekly.

**Restore drill (before the first paying customer, then now and then):**
```bash
# The restore reads from S3, so use the read-capable profile, not the server key:
AWS_PROFILE=clew-restore ./scripts/restore_postgres.sh --compare-live \
  s3://clew-db-backups/db-backups/clew_YYYYMMDDTHHMMSSZ.sql.gz clew_restore_drill
```
The script refuses to touch the live database name, refuses to reuse a name that already exists, creates the database, restores in one transaction, and prints the row count of every table. `--compare-live` also diffs those counts against the live database. Small differences are expected (the live database moved on after the backup); a missing table or a count near zero is a failed drill. The `clew` role needs `CREATEDB` for the script (`sudo -u postgres psql -c 'ALTER ROLE clew CREATEDB;'`, and `NOCREATEDB` again afterwards). Drop the throwaway database when done: `psql "$DATABASE_URL" -c 'DROP DATABASE clew_restore_drill'`.

**After any restore (drill or real recovery):** two tasks are timestamp driven and must be run by hand against the restored database, otherwise data that should be gone comes back. Set `DATABASE_URL` to the restored database for these commands only:
```bash
source .venv/bin/activate
python -c "from workers.tasks.purge_expired_data import purge_expired_data as t; print(t())"
python -c "from workers.tasks.purge_deleted_accounts import purge_deleted_accounts as t; print(t())"
```

**Secrets are not in the backup.** Keep `TOTP_ENCRYPTION_KEY`, `JWT_SECRET` and the other `.env` secrets in a password manager that is not on the server. Without the original `TOTP_ENCRYPTION_KEY`, a restored database has unreadable MFA secrets and Cloudflare tokens.

**Redis is not backed up.** Accepted: the agents re-learn each customer in about 15 batches.

**Status:** the scripts are built and tested locally. Installing the cron line on the server, taking the first real backup and running the restore drill there are done at go-live (TODO.md Phase 15).

**When to upgrade:** once monthly recurring revenue justifies it, migrate Postgres to RDS with automated daily snapshots and point-in-time recovery. On a t3.small with fewer than 10 customers, pg_dump to S3 is sufficient and costs nothing.

#### Upgrading the Server

Two minutes downtime. No data loss.

1. EC2 → tick `clew-production` → Instance state → Stop → wait
2. Actions → Instance settings → Change instance type
3. Instance state → Start
4. SSH back in: `pm2 resurrect && pm2 status`

| Type | vCPU | RAM | ~$/mo | When |
|---|---|---|---|---|
| t3.small | 2 | 2 GB | $15 | Up to ~10 customers |
| t3.medium | 2 | 4 GB | $30 | First paying customers |
| t3.large | 2 | 8 GB | $60 | Heavy log volumes |
| t3.xlarge | 4 | 16 GB | $120 | 30+ customers |

After upgrading to t3.xlarge: update `CELERY_CONCURRENCY=8` in `.env`, then `pm2 restart clew-worker`.

#### Testing Tiers Without Billing

To test Growth/Pro features locally without going through payment:

```bash
psql postgresql://clew:YOUR_DB_PASSWORD@localhost/clew
```

```sql
SELECT email, tier FROM clients WHERE email = 'your@email.com';
UPDATE clients SET tier = 'growth' WHERE email = 'your@email.com';
\q
```

Valid values: `starter`, `growth`, `pro`

---

### Staging (same EC2 server)

Staging is a second copy of the stack on the production box, used to try billing, migrations and
the CSP before they reach production. It shares the machine and nothing else.

| | Production | Staging |
|---|---|---|
| Checkout | `/home/ubuntu/abuse` | `/home/ubuntu/abuse-staging` |
| Postgres | database `clew` | database `clew_staging`, role `clew_staging` |
| Redis | database index 0 | database index 1 (`REDIS_URL=redis://localhost:6379/1`) |
| FastAPI port | 8000 | 8100 |
| Next.js port | 3000 | 3100 |
| Hosts | `www`, `dashboard`, `internal`, `api` | `stg`, `stg-dashboard`, `stg-internal`, `stg-api` (all under `clewsec.com`) |
| PM2 names | `clew-*` | `clew-stg-*` |
| Razorpay | live keys | test keys only |
| Secrets | production values | fresh values (`JWT_SECRET`, `TOTP_ENCRYPTION_KEY`), never copied from production |
| Email | Resend | `LOG_EMAILS=1` (printed to the log, nothing sent) |

The repo carries the templates: [docker/nginx.staging.conf](docker/nginx.staging.conf),
[docker/ecosystem.staging.config.js](docker/ecosystem.staging.config.js) and
[docker/staging.env.example](docker/staging.env.example) (backend `.env` plus the frontend
`.env.local` values).

**Set up (founder, once; this is the `[EXTERNAL]` part, nothing here runs from the repo):**
1. DNS: four A records (`stg`, `stg-dashboard`, `stg-internal`, `stg-api`) to the same Elastic IP
2. Postgres: `CREATE ROLE clew_staging ...` and `CREATE DATABASE clew_staging OWNER clew_staging` (commands are in `docker/staging.env.example`)
3. `git clone` the repo to `/home/ubuntu/abuse-staging`, create `.venv`, `pip install -r requirements.txt`, copy `.env` and `frontend/.env.local` from the template, `./scripts/download_geoip.sh` (or copy the two `.mmdb` files from production)
4. `alembic upgrade head` with the staging `.env`, then `cd frontend && npm ci && npm run build`
5. Nginx: copy `docker/nginx.staging.conf` to `sites-available/clew-staging`, enable it, `nginx -t`, reload, then run the `certbot --expand` line at the top of that file
6. `pm2 start docker/ecosystem.staging.config.js && pm2 save`
7. Razorpay dashboard in **test mode**: webhook `https://stg-api.clewsec.com/billing/razorpay/webhook` with events `payment.captured`, `payment.failed`, `refund.processed`, and its own signing secret
8. Create a staff user against the staging database (`scripts/create_staff_user.py` with the staging `DATABASE_URL`)

**Rules that keep it safe:**
- Never put a live Razorpay key, the production `JWT_SECRET` or the production `DATABASE_URL` in the staging `.env`. The JWT secret being different means a staging cookie cannot authenticate on production
- Deploy to staging first, run the checks below, then deploy production: `git pull`, `pip install`, `alembic upgrade head`, `npm run build`, `pm2 restart clew-stg-api clew-stg-frontend clew-stg-worker clew-stg-beat`
- Always name the process: `pm2 restart all` restarts production **and** staging

**Check after a staging deploy:**
```bash
curl -s http://127.0.0.1:8100/health          # {"status":"ok"}
curl -sI http://127.0.0.1:3100/ | head -1     # HTTP/1.1 200 OK
source .venv/bin/activate && alembic current  # the same head as the code
pm2 status                                    # every clew-stg-* process online
```
Then in a browser: register on `https://stg-dashboard.clewsec.com` (Turnstile test key always passes), run one test-mode Razorpay payment with a Razorpay test card, and confirm the bill turns paid, the receipt opens and the webhook shows as delivered in the Razorpay dashboard.

**Status:** the templates are written and checked for syntax only. Provisioning and "a staging deploy works end to end" are not done (TODO.md Phase 10).

---

### Clew Audit delivery (runbook)

Clew Audit is the one-time, sales-assisted retrospective scan (INR 49,999 / USD 599). There is no
self-serve flow and no report generator. The pricing callout is hidden until you are ready to sell;
when you are, restore it with the price above and `mailto:support@clewsec.com`.

What the code does today, because the runbook has to work inside it:
- A first connection reads only the **last 7 days** of the bucket (`workers/tasks/process_logs.py`, `list_objects_since`)
- After that, each poll reads at most **500 objects**, oldest first, forward from the cursor (`last_processed_key`)
- If `last_processed_key` names an object that no longer exists, the reader starts from the **oldest** object (`S3Reader.list_new_objects`). The runbook relies on this to reach history older than 7 days
- At the plan's monthly call volume scanning stops. The audit organization therefore needs a tier with enough volume

**Procedure (run it on the STAGING stack, never on production, so a prospect's history never touches customer data, quotas or the production Redis):**
1. Agree the window and the bucket with the prospect, and send them the normal read-only trust policy (Customer Onboarding, below). Read access only, no write, no delete
2. On staging, register an organization for the prospect (`Audit - <company>`), complete the S3 settings with their role ARN, bucket, prefix and region
3. Lift the cap for the run (staging database only): `UPDATE organizations SET tier = 'pro' WHERE id = '...';`. If the history is larger than 200M calls, split it by prefix and run it in parts
4. To go further back than 7 days, point the cursor at a key that does not exist, so the reader starts from the oldest object: `UPDATE organizations SET last_processed_key = '__audit_start__' WHERE id = '...';`
5. Let the staging worker run. Each 15-minute poll consumes up to 500 objects. Watch progress with `pm2 logs clew-stg-worker` and `SELECT last_processed_key, last_scan_status FROM organizations WHERE id = '...';`. It is finished when polls report no new objects
6. Build the findings from the `verdicts` table (columns `timestamp`, `ip`, `endpoint`, `threat_type`, `severity`, `confidence`, `explanation`, `would_have_blocked_at`, `cost_prevented`). Start with:
   ```sql
   SELECT threat_type, severity, count(*) AS verdicts, count(DISTINCT ip) AS ips
   FROM verdicts WHERE org_id = '...' GROUP BY 1, 2 ORDER BY verdicts DESC;
   ```
   Write the report by hand: summary, top attack types, top offending IPs with example endpoints, an estimate of cost prevented, and what a live subscription would have blocked
7. Send the report. Then disconnect and delete: remove the audit organization from staging (that cascades its verdicts) and ask the prospect to delete the role

**Known limits (say so in the sales call):** the retention window of the tier applies to the verdicts, so
export the report before the retention purge runs; there is no per-record scoring beyond the verdicts;
very large histories take days at 500 objects per 15 minutes.

---

### Customer Onboarding — S3 Access

Clew reads a customer's logs by assuming an IAM role in their own AWS
account (`sts:AssumeRole`, phase 2), not by holding a shared long-lived
access key. Each org gets its own server-generated External ID at creation
time (`organizations.aws_external_id`), shown read-only on the Settings
page. The settings page (`IamPolicyGuide`) generates both policies below
with the org's own External ID and Clew's account ID already filled in.

1. Customer creates an IAM role in their own AWS account with this trust
   policy (the `sts:ExternalId` condition is the part that actually enforces
   the trust, without it the role would trust *any* caller who knows Clew's
   account ID):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Principal": { "AWS": "arn:aws:iam::YOUR_CLEW_ACCOUNT_ID:root" },
       "Action": "sts:AssumeRole",
       "Condition": { "StringEquals": { "sts:ExternalId": "THEIR_ORGS_EXTERNAL_ID" } }
     }]
   }
   ```

2. Customer attaches this permissions policy to the same role (add the
   `wafv2` statement only if they intend to use blocking, manual or
   automatic, see the note below):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": ["s3:GetObject", "s3:ListBucket"],
       "Resource": ["arn:aws:s3:::THEIR-BUCKET-NAME", "arn:aws:s3:::THEIR-BUCKET-NAME/*"]
     }]
   }
   ```

3. Customer pastes the resulting role ARN back into Settings
   (`PATCH /clients/me`, `aws_role_arn`). The S3 connection test runs
   immediately.

One role, two capability sets. The S3 statement alone only grants Clew read
access to logs, it does not enable blocking (manual or automatic). A
customer who wants blocking must tick the "Also include WAF blocking
permissions" checkbox on the Settings page, which regenerates the
permissions policy JSON with both statements, and update the **same role's**
existing permissions policy with it, not create a second role. This applies
equally to a Basic-tier customer's manual blocking and a Growth-and-above
customer's automatic blocking, both go through the same `wafv2:GetIPSet`/
`wafv2:UpdateIPSet` permissions, only the trigger differs.

`YOUR_CLEW_ACCOUNT_ID` is the 12-digit number in the top-right of your AWS
console, set as `CLEW_AWS_ACCOUNT_ID` in `.env`.

Any org that has not configured `aws_role_arn` falls back to Clew's shared
IAM user (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` on the API/worker
host), the pre-phase-2 behavior. See `api/aws.py`'s `aws_session_for_org`.

**Legacy path (bucket policy, no role).** Before phase 2, a customer
granted access by attaching a bucket policy naming Clew's shared IAM user
as principal, with no External ID and no per-customer revocation. This
still works for any org still on the shared-credential fallback, kept here
only until that fallback is retired:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:ListBucket"],
    "Resource": [
      "arn:aws:s3:::THEIR-BUCKET-NAME",
      "arn:aws:s3:::THEIR-BUCKET-NAME/*"
    ],
    "Principal": { "AWS": "arn:aws:iam::YOUR_CLEW_ACCOUNT_ID:root" }
  }]
}
```

---

### Adding Razorpay Later (INR — build first)

No Plans are created in the Razorpay dashboard: billing uses one-time Orders
priced by the server from `api/tiers.py`.

1. Dashboard → Account & Settings → API keys → generate the live key pair
2. Settings → Payment capture → set to **automatic** (the server requires a
   `captured` payment)
3. Developers → Webhooks → add `https://api.clewsec.com/billing/razorpay/webhook`
   with events `payment.captured`, `payment.failed` and `refund.processed`,
   and a signing secret
4. Add to `.env`:
   ```
   RAZORPAY_KEY_ID=rzp_live_...
   RAZORPAY_KEY_SECRET=...
   RAZORPAY_WEBHOOK_SECRET=...
   ```
5. `pm2 restart clew-api`

---

### Adding Stripe Later (optional, not planned)

1. Stripe Dashboard → Developers → API keys → copy Secret key (`sk_live_...`)
2. Products → create one product per tier, two prices each (monthly INR + USD):

   | Tier | USD | INR |
   |---|---|---|
   | Starter | $49/mo | ₹1,999/mo |
   | Growth | $129/mo | ₹4,999/mo |
   | Pro | $249/mo | ₹9,999/mo |

3. Developers → Webhooks → Add endpoint: `https://api.clewsec.com/billing/webhook`
   Events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
   Copy the signing secret (`whsec_...`)
4. Add to `.env`:
   ```
   STRIPE_SECRET_KEY=sk_live_...
   STRIPE_WEBHOOK_SECRET=whsec_...
   STRIPE_PRICE_BASIC_INR=price_...
   STRIPE_PRICE_BASIC_USD=price_...
   # ... (see .env.example for full list)
   ```
5. `pm2 restart clew-api`

Test with `sk_test_...` first. Test card: `4242 4242 4242 4242`, any future expiry, any CVC.
