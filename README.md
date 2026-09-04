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
│   ├── limiter.py             <- shared slowapi rate limiter instance
│   └── routes/
│       ├── auth.py            <- register/login/MFA/sessions/password/account deletion
│       ├── clients.py         <- GET/PATCH /clients/me (org S3 + alert + blocking config)
│       ├── verdicts.py        <- list/detail/manual-block/block/unblock/threat-types
│       ├── dashboard.py       <- GET /dashboard/summary
│       ├── ips.py             <- GET /ips, POST /ips/{ip}/unblock
│       ├── billing.py         <- Stripe (pending keys) + Razorpay (live) + shared cancel/refund
│       ├── org.py             <- invites, team members, role changes, ownership transfer
│       ├── settings.py        <- POST /settings/test-waf, /settings/test-cloudflare
│       └── alerts.py          <- GET /alerts (delivery log), POST /alerts/test
│
├── db/
│   ├── models.py              <- all SQLAlchemy ORM models (Client, Organization, ...)
│   ├── session.py             <- engine + SessionLocal factory
│   └── migrations/versions/   <- 13 revisions, see `alembic history` for the current chain
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
│   ├── beat.py                <- schedule: poll every 15min, trial reminders + purge daily
│   ├── tests/                 <- test_process_logs.py (custom runner, not pytest)
│   └── tasks/
│       ├── process_logs.py            <- S3 -> detect -> verdicts + ip_memory (the main task)
│       ├── send_alerts.py             <- Resend email alerts, severity-threshold gated
│       ├── push_blocks.py             <- WAF / Cloudflare IP block tasks
│       ├── trial_reminders.py         <- 5d/2d trial-ending emails + expired-trial tier revert
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
│       │   ├── login/, register/      <- sign in, create account (Turnstile-gated)
│       │   ├── verify-email/          <- OTP confirmation
│       │   ├── forgot-password/, reset-password/  <- Turnstile-gated reset flow
│       │   ├── accept-invite/         <- team invite acceptance (new or existing account)
│       │   ├── legal/                 <- terms, privacy, dpa, subscription-agreement, refund-policy
│       │   └── dashboard/
│       │       ├── layout.tsx         <- sidebar + StatusHeader + DashboardGate wrapper
│       │       ├── page.tsx           <- overview (stats, chart, top IPs, scanning banner)
│       │       ├── alerts/page.tsx    <- Verdicts + Notifications tabs
│       │       ├── ips/page.tsx       <- All IPs + Blocked tabs
│       │       ├── verdicts/[id]/     <- verdict detail (agent scores, raw logs, AI analysis)
│       │       └── settings/page.tsx  <- S3/WAF/Cloudflare config, MFA, team, billing
│       ├── components/
│       │   ├── home/                  <- Hero, CostCalculator, HowItWorks, Pricing
│       │   ├── layout/                <- Navbar, Footer
│       │   ├── legal/                 <- LegalLayout (scroll-spy TOC sidebar)
│       │   ├── dashboard/              <- Sidebar, StatusHeader, TeamMembers, tab components
│       │   ├── auth/                  <- AuthLayout, Turnstile widget wrapper
│       │   └── providers/             <- ThemeProvider (next-themes)
│       ├── lib/                       <- api.ts (apiFetch w/ silent refresh), razorpay.ts
│       └── proxy.ts                   <- Edge auth gatekeeper (Next.js 16's middleware.ts)
│
├── docker/
│   ├── docker-compose.yml     <- local Postgres + Redis
│   ├── nginx.conf             <- production Nginx config (CSP, security headers)
│   └── ecosystem.config.js    <- PM2 process config, copy to repo root when deploying
│
├── scripts/
│   ├── download_geoip.sh      <- fetches GeoLite2-City + GeoLite2-ASN .mmdb files
│   └── generate_promo_codes.py <- idempotent launch promo-code generator
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
| Billing | Razorpay (INR) + Stripe (USD) | Razorpay first target; Stripe pending company registration |
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
Put the local-only `DATABASE_URL`, `FRONTEND_URL=http://localhost:3000`,
`COOKIE_DOMAIN=` (blank), `DEBUG=1`, and the Turnstile test key above into
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
# Create frontend/.env.local with:
# NEXT_PUBLIC_API_URL=http://localhost:8000
# JWT_SECRET=<same value as backend .env>
npm install
npm run dev
```

Frontend: `http://localhost:3000`

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
| `verify_token_hash` / `reset_token_hash` (+ `_expires_at`) | text / timestamptz | Hashed OTPs, never stored raw |
| `deleted_at` | timestamptz | Item 40 soft-delete marker; hard-purged 30 days later |

**`organizations`**: one row per tenant, owns everything else

| Column | Type | Notes |
|---|---|---|
| `id` / `company_name` / `domain` | UUID / varchar / varchar | domain drives invite role-ceiling checks |
| `s3_bucket` / `s3_prefix` / `log_format` / `aws_region` | varchar | Customer's log source config |
| `last_processed_key` / `s3_connected_at` | text / timestamptz | Ingestion cursor + first-connect timestamp |
| `s3_status` / `s3_status_message` | varchar / text | Set on log-format auto-detect mismatch (item 5) |
| `calibration_status` | varchar | `running` / `done` / `failed`, first-connection LTM warmup |
| `last_scan_completed_at` / `last_scan_status` / `last_scan_error` | timestamptz / varchar / text | |
| `home_country` | varchar(2) | Feeds `GeoIPAgent`'s off-country baseline |
| `waf_ip_set_id` / `cloudflare_zone_id` / `cloudflare_token` / `blocking_tos_accepted_at` | | Blocking config, Growth+ only |
| `alert_email` / `alert_severity_threshold` | varchar | `all` or `high_critical_only` |
| `tier` | varchar | `free` / `starter` / `growth` / `pro` |
| `trial_source` / `trial_ends_at` / `pilot_code_used` / `trial_reminder_{5,2}d_sent` | | Item 11 trial billing |
| `billing_provider` | varchar | `stripe` / `razorpay` / `pilot` |
| `stripe_customer_id` / `stripe_subscription_id` | varchar | Pending live keys |
| `razorpay_customer_id` / `razorpay_subscription_id` / `next_billing_date` / `first_charged_at` | | Live billing path |
| `gstin` | varchar | Optional, India only |
| `monthly_requests_processed` / `monthly_requests_reset_at` | int / date | Columns exist; usage metering (item 30) is post-MVP, not enforced yet |
| `deleted_at` | timestamptz | Owner-deletes-account cascades here (item 40) |

**`organization_members`**: many-to-many, a client's role within an org (`owner` / `admin` / `viewer`, unique on the pair)

**`org_invites`**: single-use directed invite tokens: `invited_email`, `role`, `token_hash`, `expires_at`, `accepted_at`

**`promo_codes`**: item 26 launch codes: `code` (unique), linked Stripe coupon / Razorpay offer ID (nullable, filled in later), `redeemed_at`, `redeemed_by_org_id`

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
POST /verdicts/{id}/block         Enqueue WAF/Cloudflare block (Growth/Pro, owner/admin, ToS-gated)
POST /verdicts/{id}/unblock       Enqueue unblock
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

### Billing: `api/routes/billing.py`
```
GET  /billing/status                          Current tier + subscription state
POST /billing/checkout                        Stripe Checkout Session (pending live keys)
POST /billing/portal                          Stripe Customer Portal Session
POST /billing/webhook                         Stripe webhook (verify signature + update tier)

POST /billing/razorpay/create-subscription    Create/upgrade/downgrade a Razorpay subscription
POST /billing/razorpay/verify-payment         Optimistic tier update right after checkout
POST /billing/razorpay/webhook                Authoritative tier reconciliation (HMAC verified)

GET  /billing/refund-eligibility              72h remorse-window check
POST /billing/cancel                          Cancel (Razorpay), immediate or at-cycle-end
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
  timezone/off-hours history, robust-estimator lock state, persisted to Redis key
  `clew:ltm:{org_id}` after every batch

`ProductSharedMemory` (subclasses `SharedMemory`) loads LTM from Redis on init
and calls `mem.flush()` to write back after each batch. Worker restarts and
redeployments do not lose detection context.

### Known limitation

Pass B's per-IP focus pass needs ≥20 requests/IP/poll to trigger; thousands of
low-volume IPs can evade both passes. Cross-IP clustering to catch this is a
Pro-tier roadmap item, not built yet.

### Import path setup

`detection/engine/pipeline/run.py` inserts `detection/` onto `sys.path` at import
time, so `from engine.xxx` and `from schemas.models` resolve correctly regardless
of Celery's working directory.

---

## Celery Pipeline

### Beat-scheduled tasks (`workers/beat.py`)

| Task | Schedule | Purpose |
|---|---|---|
| `poll_all_clients` | every 15 min | Fans out one `process_logs` per org with S3 configured (skips expired-unpaid-trial and soft-deleted orgs) |
| `send_trial_reminders` | daily 09:00 UTC | 5-day and 2-day trial-ending emails; reverts tier to `free` on actual expiry |
| `purge_deleted_accounts` | daily 03:00 UTC | Hard-deletes orgs/clients soft-deleted 30+ days ago |

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
10. Ping `CRONITOR_URL` in the `finally` block if set (never fails the scan)

**`send_alerts`**: Resend email, respects `alert_severity_threshold`. Deduplicates via
`alerts_sent`.

**`push_blocks`**: Checks tier ≥ growth, confidence ≥ 0.75, and that
`blocking_tos_accepted_at` is set, then calls `blocking/aws_waf.py` and/or
`blocking/cloudflare.py` independently (one can succeed while the other fails).

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
| `/` | Server | Marketing homepage: Hero, CostCalculator, HowItWorks, Pricing, Footer |
| `/pricing` | Server | Standalone pricing comparison page |
| `/legal/*` | Client | terms, privacy, dpa, subscription-agreement, refund-policy (scroll-spy TOC) |
| `/login` | Client | Email + password |
| `/register` | Client | Email + password + company name, Turnstile CAPTCHA, promo code, ToS checkbox |
| `/verify-email` | Client | 6-digit OTP input |
| `/forgot-password` | Client | Email field + Turnstile (anti-enumeration: always shows "if registered, check email") |
| `/reset-password` | Client | Email + OTP + new password |
| `/accept-invite` | Client | Reads `?token=`, handles new-account / existing-account / expired / already-used |
| `/dashboard` | Client | Stats grid, trend chart, top IPs, scanning banner, empty states |
| `/dashboard/alerts` | Client | "Verdicts" + "Notifications" tabs (delivery log, test-alert button) |
| `/dashboard/ips` | Client | "All IPs" + "Blocked" tabs, manual block form |
| `/dashboard/verdicts/[id]` | Client | Agent-score table, raw log sample, AI analysis (tier-gated), block/unblock |
| `/dashboard/settings` | Client | S3/WAF/Cloudflare config, MFA, team, billing, change password, delete account |

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

### Cross-origin cookies

`COOKIE_DOMAIN=.clewsec.com` means cookies set by `api.clewsec.com` are sent to
all subdomains including `www.clewsec.com`. `allow_credentials=True` + the exact
`FRONTEND_URL` in CORS config are both required for this to work.

---

## Blocking Integrations

Growth and Pro tiers only, and gated behind a one-time blocking ToS acceptance
(`POST /clients/me/accept-blocking-tos`) before either can be used to actively
block (unblock is never gated).

**AWS WAF v2** (`blocking/aws_waf.py`): adds/removes IPs from a customer-owned
WAF IP set. The customer creates the IP set, configures Clew's IAM role as a
trusted principal, and stores the IP set ARN in Settings. Clew's IAM role needs
`wafv2:GetIPSet` + `wafv2:UpdateIPSet` on that resource.

**Cloudflare** (`blocking/cloudflare.py`): creates/deletes block rules on the
customer's zone using the Cloudflare API. `cloudflare_zone_id` and
`cloudflare_token` stored per-org in the `organizations` table.

Both can be configured simultaneously, high-confidence threats are blocked on
all configured integrations, and each tracks its own `*_blocked` / `*_block_error`
state independently in `ip_memory` (one can fail while the other succeeds).

---

## Billing

Razorpay (INR) is the live path; Stripe (USD) is fully written but pending
live API keys (see "What Is Not Yet Active" below).

**Razorpay flow:**
1. User picks a plan in Settings → `POST /billing/razorpay/create-subscription`
   → Razorpay Checkout opens client-side (`lib/razorpay.ts`)
2. On success, the frontend calls `POST /billing/razorpay/verify-payment`
   (optimistic tier update for immediate UX)
3. Razorpay also sends `subscription.activated`/`halted`/`cancelled` and
   `payment.failed` webhooks to `POST /billing/razorpay/webhook` (HMAC
   verified against `RAZORPAY_WEBHOOK_SECRET`), authoritative, reconciles
   any case the checkout-time call missed (e.g. a deferred downgrade)
4. Upgrade = cancel old subscription now + start new immediately. Downgrade =
   cancel old at cycle end + start new then. First-ever payment method uses a
   calendar-anchor rule instead (on/before the 15th → immediate, after → 1st
   of next month)
5. Cancel: `POST /billing/cancel`. Refund-eligible within a 72-hour remorse
   window from `first_charged_at` (`GET /billing/refund-eligibility`)

**Stripe flow (code complete, not live):**
1. User clicks Upgrade → `POST /billing/checkout` → FastAPI creates a Stripe
   Checkout Session → redirects to Stripe's hosted payment page
2. Stripe sends `checkout.session.completed` to `POST /billing/webhook`
3. Webhook verifies the Stripe signature, sets `org.tier` + subscription IDs

**Trials & promo codes:** every signup gets a trial (7 days self-serve, 30
days with a valid promo code from the `promo_codes` table). A daily Beat task
reverts the tier to `free` once an unpaid trial's `trial_ends_at` passes.

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
`RAZORPAY_WEBHOOK_SECRET` + 6 `RAZORPAY_PLAN_*` IDs (see "Adding Razorpay Later").

---

## What Is Not Yet Active

- **Stripe billing (USD)**: code complete, DB migration applied, but blocked on
  live API keys pending company registration. Razorpay (INR) is the live path
  today; see "Adding Stripe Later" once keys exist.
- **Sentry / exception tracking, a public status page, an internal ops panel,
  and a staging environment**: all explicitly post-MVP (see TODO.md's
  "Operations, deferred" section). None of these block onboarding a first
  real client; revisit when there's an actual client/audience to justify them.
- **Usage metering**: `organizations.monthly_requests_processed` exists but
  nothing increments it yet; no tier is anywhere near a volume limit.
- **Webhook/Slack/PagerDuty alert channels, a public customer-facing API +
  API keys, Groq-generated verdict explanations**: all post-MVP, no
  customer has asked for any of them yet.

---

## Testing and Deployment

This is a linear walkthrough for deploying to production. Do every step in order.
When it says "on your laptop" it means a terminal on your local machine, not the SSH session.

---

### What you will end up with

- `https://clewsec.com` — Next.js frontend
- `https://api.clewsec.com` — FastAPI backend
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
- `FRONTEND_URL=https://clewsec.com`
- `COOKIE_DOMAIN=.clewsec.com`
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
NEXT_PUBLIC_API_URL=https://api.clewsec.com
NEXT_PUBLIC_SITE_URL=https://clewsec.com
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

**Layer 1 (HTTP uptime, UptimeRobot, free):**
1. [uptimerobot.com](https://uptimerobot.com) → Add New Monitor → HTTP(s)
2. URL: `https://api.clewsec.com/health`
3. Interval: 5 minutes
4. Add your email as an alert contact

**Layer 2 (Beat task heartbeat, Cronitor, free tier):**
1. [cronitor.io](https://cronitor.io) → Add Monitor → Heartbeat
2. Set the expected window to 25 minutes (slightly over the 15-minute poll interval): if no ping arrives within the window, Cronitor emails you
3. Copy the monitor's Ping URL into `CRONITOR_URL` in `/home/ubuntu/abuse/.env`
4. `pm2 restart clew-worker` so the new env var is picked up

`process_logs` already pings `CRONITOR_URL` at the end of every run (success or failure) if the variable is set, no further code changes needed. Leave `CRONITOR_URL` blank in any non-production `.env`.

Layer 3 (Sentry exception tracking) is post-MVP, see item 46 in the project TODO.

---

### Phase 5 — Nginx

```bash
sudo nano /etc/nginx/sites-available/clew
```

Paste:
```nginx
server {
    server_name clewsec.com www.clewsec.com;
    listen 80;
    location / {
        proxy_pass         http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade       $http_upgrade;
        proxy_set_header   Connection    'upgrade';
        proxy_set_header   Host          $host;
        proxy_set_header   X-Real-IP     $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }
}

server {
    server_name api.clewsec.com;
    listen 80;
    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

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
ping clewsec.com       # must show YOUR Elastic IP
ping api.clewsec.com   # must show YOUR Elastic IP
```

```bash
sudo certbot --nginx -d clewsec.com -d www.clewsec.com -d api.clewsec.com
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
        NODE_ENV:             'production',
        NEXT_PUBLIC_API_URL:  'https://api.clewsec.com',
        NEXT_PUBLIC_SITE_URL: 'https://clewsec.com',
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
# Expected: e3c1a7f920d4 (head)

# All processes running
pm2 status
```

Browser checklist:

| URL | Expected |
|---|---|
| `https://clewsec.com` | Marketing homepage, padlock visible |
| `https://api.clewsec.com/health` | `{"status":"ok"}` |
| `http://clewsec.com` | Redirects to https:// |
| `https://clewsec.com/register` | Registration form loads |

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
`pg_dump` to S3 is the MVP backup strategy.

**Set up the backup bucket (once):**
1. S3 → Create bucket → `clew-db-backups`
2. Add a lifecycle rule on the bucket deleting objects older than 30 days
3. Attach `s3:PutObject` on this bucket to the `clew-server` IAM user (step 1.1), in addition to its existing WAF permissions, as a separate statement scoped to the backup bucket only

**Add the nightly backup to crontab:**
```bash
crontab -e
# Add this line:
0 2 * * * pg_dump postgresql://clew:PASSWORD@localhost/clew | gzip > /tmp/clew_$(date +\%Y\%m\%d).sql.gz && aws s3 cp /tmp/clew_$(date +\%Y\%m\%d).sql.gz s3://clew-db-backups/db-backups/ && rm /tmp/clew_$(date +\%Y\%m\%d).sql.gz
```

**Test restore before the first paying customer:**
```bash
aws s3 cp s3://clew-db-backups/db-backups/clew_YYYYMMDD.sql.gz .
gunzip < clew_YYYYMMDD.sql.gz | psql postgresql://clew:PASSWORD@localhost/clew
```

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

### Customer Onboarding — S3 Access

When a customer connects their S3 bucket, they add this policy to their bucket in their own AWS account:

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

`YOUR_CLEW_ACCOUNT_ID` is the 12-digit number in the top-right of your AWS console. Give this to customers during onboarding.

---

### Adding Razorpay Later (INR — build first)

1. Razorpay Dashboard → Products → Plans → create 6 plans (Starter/Growth/Pro × Monthly/Annual)
2. Copy each Plan ID
3. Add to `.env`:
   ```
   RAZORPAY_KEY_ID=rzp_live_...
   RAZORPAY_KEY_SECRET=...
   RAZORPAY_PLAN_STARTER_MONTHLY_INR=plan_...
   # ... (see .env.example for full list)
   ```
4. `pm2 restart clew-api`

---

### Adding Stripe Later (USD — after company registration)

1. Stripe Dashboard → Developers → API keys → copy Secret key (`sk_live_...`)
2. Products → create one product per tier, two prices each (monthly INR + USD):

   | Tier | USD | INR |
   |---|---|---|
   | Starter | $39/mo | ₹2,999/mo |
   | Growth | $69/mo | ₹4,999/mo |
   | Pro | $129/mo | ₹9,999/mo |

3. Developers → Webhooks → Add endpoint: `https://api.clewsec.com/billing/webhook`
   Events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
   Copy the signing secret (`whsec_...`)
4. Add to `.env`:
   ```
   STRIPE_SECRET_KEY=sk_live_...
   STRIPE_WEBHOOK_SECRET=whsec_...
   STRIPE_PRICE_STARTER_INR=price_...
   STRIPE_PRICE_STARTER_USD=price_...
   # ... (see .env.example for full list)
   ```
5. `pm2 restart clew-api`

Test with `sk_test_...` first. Test card: `4242 4242 4242 4242`, any future expiry, any CVC.
