# Clew — Developer Guide

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

**Target customers:** Series A/B SaaS companies and SMBs with public APIs and no
dedicated security team.

**Tiers:**
| Tier | Price | Core features |
|---|---|---|
| Free | $0 | Monitoring + dashboard, 7-day history |
| Starter | $99/mo | All Free + 90-day history + email alerts |
| Growth | $249/mo | All Starter + auto-blocking via WAF/Cloudflare |
| Pro | $449/mo | All Growth + aggressive blocking threshold + priority support |

---

## Repository Structure

```
abuse/                         <- project root (repo: "abuse", product: Clew)
├── api/                       <- FastAPI backend
│   ├── main.py                <- app entry point, CORS, routers wired in
│   ├── deps.py                <- get_db(), get_current_client() dependencies
│   ├── auth_utils.py          <- hashing, JWT, cookies, OTP, Resend email
│   ├── limiter.py             <- shared slowapi rate limiter instance
│   └── routes/
│       ├── auth.py            <- all auth endpoints (register, login, OAuth, MFA)
│       ├── clients.py         <- GET/PATCH /clients/me (S3 config + alerts)
│       ├── verdicts.py        <- GET /verdicts, manual block/unblock
│       ├── dashboard.py       <- GET /dashboard/summary
│       ├── ips.py             <- GET /ips (IP intelligence table)
│       └── billing.py         <- Stripe checkout, portal, webhook
│
├── db/
│   ├── models.py              <- all SQLAlchemy ORM models (7 tables)
│   ├── session.py             <- engine + SessionLocal factory
│   └── migrations/versions/
│       ├── c957d12130b9_initial_schema.py
│       ├── b4e8f2a1c953_add_stripe_billing_columns.py
│       └── e3c1a7f920d4_add_mfa_backup_codes.py
│
├── engine/                    <- AI detection engine
│   ├── engine -> source       <- symlink: makes `from engine.xxx` work
│   ├── schemas/models.py      <- LogRecord pydantic model
│   └── source/
│       ├── agents/            <- 7 detection agents
│       ├── coordinator/       <- MetaAgentOrchestrator (fusion + XGB)
│       ├── memory/
│       │   ├── shared_memory.py       <- in-process STM + LTM base class
│       │   └── product_memory.py      <- Redis-backed LTM for production
│       ├── pipeline/run.py            <- run_pipeline() — Celery entry point
│       └── ingestion/
│           ├── s3_reader.py           <- list + download S3 log objects
│           ├── apigw_parser.py        <- AWS API Gateway log parser
│           ├── alb_parser.py          <- AWS ALB log parser
│           └── normalizer.py          <- routes to correct parser, batches
│
├── workers/
│   ├── celery_app.py          <- Celery app instance + config
│   ├── beat.py                <- periodic schedule (poll every 15 min)
│   └── tasks/
│       ├── process_logs.py    <- S3 -> detect -> verdicts + ip_memory
│       ├── send_alerts.py     <- Resend email alerts for high/critical
│       └── push_blocks.py     <- WAF / Cloudflare IP block tasks
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
│       │   ├── not-found.tsx          <- custom 404
│       │   ├── global-error.tsx       <- global error boundary
│       │   ├── sitemap.ts             <- /sitemap.xml
│       │   ├── robots.ts              <- /robots.txt
│       │   ├── pricing/page.tsx       <- standalone /pricing route
│       │   ├── login/                 <- sign in + OAuth
│       │   ├── register/              <- create account
│       │   ├── verify-email/          <- OTP confirmation
│       │   ├── forgot-password/       <- request reset
│       │   ├── reset-password/        <- enter OTP + new password
│       │   └── dashboard/
│       │       ├── layout.tsx         <- sidebar + content wrapper
│       │       ├── page.tsx           <- overview (stats, chart, top IPs)
│       │       ├── alerts/page.tsx    <- paginated verdict feed
│       │       ├── ips/page.tsx       <- IP intelligence table
│       │       └── settings/page.tsx  <- S3 config, MFA, sessions, billing
│       ├── components/
│       │   ├── home/                  <- Hero, CostCalculator, HowItWorks, Pricing
│       │   ├── layout/                <- Navbar, Footer
│       │   ├── dashboard/             <- Sidebar
│       │   ├── auth/                  <- AuthLayout (shared card wrapper)
│       │   └── providers/             <- ThemeProvider (next-themes)
│       ├── lib/api.ts                 <- API_URL constant
│       └── middleware.ts              <- Edge auth gatekeeper
│
├── docker/
│   ├── docker-compose.yml     <- local Postgres + Redis
│   ├── nginx.conf             <- production Nginx config
│   └── ecosystem.config.js    <- PM2 process config
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
| Email | Resend | Transactional verification + alert emails |
| Billing | Stripe | Subscription management (keys pending) |
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
git clone <repo> clew && cd clew
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

# Load env and apply migrations
set -o allexport && source .env && set +o allexport
alembic upgrade head

# Start API with hot reload
uvicorn api.main:app --reload --port 8000
```

API: `http://localhost:8000` | Docs: `http://localhost:8000/docs`

### 5. Celery workers
```bash
# Terminal 2 — Worker
source .venv/bin/activate && set -o allexport && source .env && set +o allexport
celery -A workers.celery_app worker --loglevel=info

# Terminal 3 — Beat scheduler
source .venv/bin/activate && set -o allexport && source .env && set +o allexport
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

### Full flow smoke test
1. Register at `/register`
2. The verification OTP prints to the FastAPI terminal (because `LOG_EMAILS=1`)
3. Paste OTP at `/verify-email`
4. Log in → reach `/dashboard`

---

## Database

### Tables

**`clients`** — one row per customer account

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `email` | varchar | Unique, indexed |
| `password_hash` | varchar | Null for OAuth-only accounts |
| `company_name` | varchar | |
| `email_verified` | bool | Must be True before login allowed |
| `s3_bucket` | varchar | Customer's log bucket |
| `s3_prefix` | varchar | Optional key prefix filter |
| `log_format` | varchar | `apigw` or `alb` |
| `aws_region` | varchar | Bucket region |
| `last_processed_key` | varchar | Last S3 key read; worker starts from here |
| `tier` | varchar | `free` / `starter` / `growth` / `pro` |
| `mfa_enabled` | bool | |
| `mfa_secret` | varchar | Fernet-encrypted TOTP secret |
| `stripe_customer_id` | varchar | |
| `stripe_subscription_id` | varchar | |
| `tier_expires_at` | timestamptz | |
| `alerts_enabled` | bool | |
| `alert_email` | varchar | Where to send alerts (defaults to login email) |
| `waf_ip_set_id` | varchar | Customer's WAF IP set ARN |
| `cloudflare_zone_id` | varchar | |
| `cloudflare_token` | varchar | Encrypted at rest |

**`oauth_accounts`** — links a provider identity to a client

One client can have multiple OAuth accounts (Google AND GitHub, for example).
Unique constraint on `(provider, provider_id)`.

**`refresh_tokens`** — active browser sessions

One row per logged-in session. Stored as SHA-256 hash — raw token only lives
in the httpOnly cookie. Set `revoked=True` to invalidate. Used for the "view
and revoke sessions" feature in Settings.

**`verdicts`** — detection results

One row per pipeline run (one per client per 15-min batch). Key columns:
`ip`, `threat_type`, `severity` (critical/high/medium/low), `confidence` (0–1),
`agents_triggered` (JSON array), `explanation`, `blocked`, `cost_prevented`.

**`ip_memory`** — IP intelligence profiles

One row per `(client_id, ip)` pair. Updated on every detection run. Powers
the IPs page. Columns: `first_seen`, `last_seen`, `total_requests`,
`threat_count`, `risk_score`, `geo_country`.

**`alerts_sent`** — notification deduplication

One row per `(verdict_id, channel)` that has been notified. Prevents duplicate
emails on Celery retries.

**`mfa_backup_codes`** — TOTP recovery

10 hashed single-use codes per client. Used when the user loses their
authenticator app.

### Migration workflow
```bash
# Apply all pending
alembic upgrade head

# After changing db/models.py
alembic revision --autogenerate -m "describe_change"
alembic upgrade head

# Check current state
alembic current

# Roll back one
alembic downgrade -1
```

---

## Backend API

All routes registered in `api/main.py`. Protected routes require the
`access_token` httpOnly cookie (set automatically at login).

### Auth — `api/routes/auth.py`

```
POST /auth/register                 Create account
POST /auth/verify-email             Submit OTP from email
POST /auth/resend-verification      Re-send OTP
POST /auth/login                    Credentials login — sets cookies
POST /auth/logout                   Clear cookies, revoke session
POST /auth/refresh                  Silent token refresh (called by middleware)
GET  /auth/me                       Current client profile

POST /auth/forgot-password          Request password reset OTP
POST /auth/reset-password           Email + OTP + new password

GET  /auth/google                   Start Google OAuth
GET  /auth/google/callback          Google callback
GET  /auth/github                   Start GitHub OAuth
GET  /auth/github/callback          GitHub callback
GET  /auth/microsoft                Start Microsoft Entra OAuth
GET  /auth/microsoft/callback       Microsoft callback

POST /auth/mfa/setup                Generate TOTP secret + QR URI
POST /auth/mfa/verify               Confirm TOTP code, enable MFA, get backup codes
POST /auth/mfa/disable              Disable MFA
POST /auth/login/mfa                Submit TOTP code during login challenge

GET    /auth/sessions               List active sessions
DELETE /auth/sessions/{id}          Revoke one session
DELETE /auth/sessions               Revoke all (logout all devices)
```

### Client config — `api/routes/clients.py`
```
GET  /clients/me    S3 config + blocking config + alert settings
PATCH /clients/me   Update any client config field
```

### Verdicts — `api/routes/verdicts.py`
```
GET  /verdicts              Paginated (filter by severity, IP, date range)
GET  /verdicts/{id}         Single verdict with full agent breakdown
POST /verdicts/{id}/block   Enqueue WAF/Cloudflare block (Growth/Pro only)
POST /verdicts/{id}/unblock Enqueue unblock
```

### Dashboard — `api/routes/dashboard.py`
```
GET /dashboard/summary?days=7   Totals, by_severity, trend, top_ips, cost_prevented
```

### IPs — `api/routes/ips.py`
```
GET /ips    Paginated ip_memory rows (sortable, filterable by country)
```

### Billing — `api/routes/billing.py`
```
GET  /billing/status       Current tier + subscription state
POST /billing/checkout     Create Stripe Checkout Session
POST /billing/portal       Create Stripe Customer Portal Session
POST /billing/webhook      Stripe webhook handler (verify signature + update tier)
```

---

## Authentication — How It Works

**Two-token system, both httpOnly cookies:**

- **Access token** — 15-minute JWT. Validated on every protected request by
  `api/deps.py::get_current_client()`. `type: "access"` claim prevents a refresh
  token being used as an access token.

- **Refresh token** — 7-day JWT. Stored as SHA-256 hash in `refresh_tokens` table.
  When the access token expires, Next.js middleware automatically calls
  `/auth/refresh` — the user never sees a session expiry.

**Token rotation:** Each call to `/auth/refresh` revokes the old token and issues
a new pair. If a refresh token is stolen and used, the victim's next genuine refresh
attempt will fail (the token was revoked), alerting them that something is wrong.

**Password hashing:** SHA-256 pre-hash → bcrypt(rounds=12). Pre-hashing prevents
bcrypt's 72-byte truncation issue for long passwords.

**OAuth (Google / GitHub / Microsoft) flow:**
1. `GET /auth/{provider}` generates a PKCE state token, stores it in Redis for
   10 min, redirects to provider's consent page
2. Provider redirects back to `/auth/{provider}/callback?code=...&state=...`
3. Server validates state (CSRF check), exchanges code for user profile
4. `_handle_oauth_sign_in()`: find existing account by provider ID, or by email
   (link), or create new account
5. Issue JWT cookies, redirect to `/dashboard`

**MFA (TOTP) flow:**
- Setup: `POST /auth/mfa/setup` returns an `otpauth://` URI. User scans with any
  authenticator app. `POST /auth/mfa/verify` confirms and enables MFA, returns
  10 backup codes.
- Login with MFA: `POST /auth/login` returns `{"mfa_required": true, "mfa_token": "..."}`.
  Frontend shows TOTP prompt. `POST /auth/login/mfa` validates and issues cookies.
- TOTP secret stored Fernet-encrypted in DB. Requires `TOTP_ENCRYPTION_KEY` env var.

---

## The Detection Engine

### Seven agents run in parallel

| Agent | Signal | Algorithm |
|---|---|---|
| `VolumeAgent` | DoS / floods | Isolation Forest on request rate |
| `TemporalAgent` | Bot timing, off-hours patterns | FFT + CUSUM |
| `AuthAgent` | Brute force, credential stuffing | Failed login rate analysis |
| `PayloadAgent` | SQLi, XSS, path traversal | Pattern matching |
| `SequenceAgent` | Endpoint enumeration | Sequence pattern analysis |
| `GeoIPAgent` | Geographic anomalies | Graph-based clustering |
| `KnowledgeAgent` | Cross-session threat memory | Known signature matching |

### Orchestrator — `engine/source/coordinator/meta_agent.py`

`MetaAgentOrchestrator` collects all 7 agent confidence scores and fuses them via:
1. Weighted average (per-agent weights tuned on training data)
2. XGBoost stacking model (trained on combined scores)
3. Conflict resolution rules

Output: `FusionVerdict` — 0–1 confidence score + explanation + agents triggered.

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
    client_id="uuid-string",
    redis_client=redis_conn,
)
# Returns a dict ready to INSERT into the verdicts table
```

### State persistence — LTM in Redis

The engine has two memory tiers:
- **STM** (Short-Term Memory) — in-process sliding window, lives for one task
  invocation only
- **LTM** (Long-Term Memory) — baseline rates, IAT reference pools, agent history,
  persisted to Redis key `clew:ltm:{client_id}` after every batch

`ProductSharedMemory` (subclasses `SharedMemory`) loads LTM from Redis on init
and calls `mem.flush()` to write back after each batch. Worker restarts and
redeployments do not lose detection context.

### The import symlink

```
engine/engine -> source    (symlink)
```

This lets `from engine.agents.xxx import ...` resolve correctly when the project
root is on `sys.path`. `engine/source/pipeline/run.py` inserts the engine root
onto `sys.path` automatically at import time.

---

## Celery Pipeline

### Three task types

**`process_logs`** (the main task, runs per client per poll):
1. Load client from DB
2. S3Reader: enumerate new objects since `last_processed_key`
3. Parse + normalize log lines to dicts (500-record batches)
4. Call `run_pipeline()` per batch
5. Insert `verdicts`, upsert `ip_memory`
6. Update `client.last_processed_key`
7. Trigger `send_alerts` for high/critical verdicts
8. Trigger `push_block` for Growth/Pro clients with high confidence

**`send_alerts`**: Resend email for high/critical verdicts. Deduplicates via
`alerts_sent` table — won't re-send on Celery retries.

**`push_block`**: Checks tier ≥ growth and confidence ≥ 0.75, then calls
`blocking/aws_waf.py` and/or `blocking/cloudflare.py`. Sets `verdict.blocked = True`.

### Beat schedule (`workers/beat.py`)

`poll_all_clients` runs every 15 minutes. Queries all clients with `s3_bucket`
set and fans out one `process_logs` task per client. No beat restart needed when
new clients sign up.

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
| `/login` | Client | Credentials + Google/GitHub/Microsoft login |
| `/register` | Client | Email + password + company name |
| `/verify-email` | Client | 6-digit OTP input |
| `/forgot-password` | Client | Email field (anti-enumeration: always shows "if registered, check email") |
| `/reset-password` | Client | Email + OTP + new password |
| `/dashboard` | Client | Stats grid, 7/30d trend chart, top IPs, recent verdicts |
| `/dashboard/alerts` | Client | Paginated verdict feed, filters, manual block button |
| `/dashboard/ips` | Client | IP intelligence table, sortable |
| `/dashboard/settings` | Client | S3 config, alert settings, MFA, sessions, billing |

### Auth middleware — `frontend/src/middleware.ts`

Runs at the Edge (Web Crypto API, no Node.js) on every request before React:
- `/dashboard/*`: verify `access_token` JWT with `jose`. If expired, call
  `POST /auth/refresh` silently. If refresh fails, redirect to `/login?next=<path>`.
- Auth pages: if already authenticated, redirect to `/dashboard`.

### Data fetching pattern

Every dashboard page is a Client Component. On mount it fetches from the API
with `{ credentials: "include" }` to send the auth cookies cross-origin. A 401
response → redirect to `/login`.

### Cross-origin cookies

`COOKIE_DOMAIN=.clewsec.com` means cookies set by `api.clewsec.com` are sent to
all subdomains including `www.clewsec.com`. `allow_credentials=True` + the exact
`FRONTEND_URL` in CORS config are both required for this to work.

---

## Blocking Integrations

Growth and Pro tiers only.

**AWS WAF v2** (`blocking/aws_waf.py`): adds/removes IPs from a customer-owned
WAF IP set. The customer creates the IP set, configures Clew's IAM role as a
trusted principal, and stores the IP set ARN in Settings. Clew's IAM role needs
`wafv2:GetIPSet` + `wafv2:UpdateIPSet` on that resource.

**Cloudflare** (`blocking/cloudflare.py`): creates/deletes block rules on the
customer's zone using the Cloudflare API. `cloudflare_zone_id` and
`cloudflare_token` stored per-client in the `clients` table.

Both can be configured simultaneously — high-confidence threats are blocked on
all configured integrations.

---

## Billing (Stripe — pending keys)

All Stripe code is written and the DB migration is applied. Integration is blocked
only on having API keys.

**Flow:**
1. User clicks Upgrade in Settings → `POST /billing/checkout` → FastAPI creates
   Stripe Checkout Session → redirects to Stripe's hosted payment page
2. Stripe sends `checkout.session.completed` webhook to `POST /billing/webhook`
3. Webhook verifies Stripe signature, sets `client.tier` + subscription IDs in DB
4. On cancel/downgrade: `customer.subscription.updated` → tier set back to `free`

**Currency:** auto-detected from browser timezone (Kolkata/India → INR, else USD).
Toggle available on the pricing page.

**What to do when keys arrive:** see the "Adding Stripe Later" section in
`DEPLOYMENT.md`.

---

## Common Development Tasks

### Add a new API endpoint

1. Add a function to an existing file in `api/routes/` (or create a new file)
2. Use `router = APIRouter()` at the top of new files
3. Wire new files into `api/main.py` with `app.include_router(router)`
4. Protected routes: add `client: Client = Depends(get_current_client)`
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
set -o allexport && source .env && set +o allexport
python -m pytest engine/source/tests/ -v
```

### Inspect Redis

```bash
redis-cli
> KEYS clew:*
> GET clew:ltm:<client_id>
```

### Connect to DB

```bash
psql postgresql://clew:password@localhost:5432/clew
\dt         # list tables
\d clients  # describe a table
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
| `JWT_SECRET` | 64-char hex — shared between backend `.env` and `frontend/.env.local` |
| `TOTP_ENCRYPTION_KEY` | Fernet key — generated with `Fernet.generate_key()` |

Set `LOG_EMAILS=1` locally to print all sent emails to terminal instead of
sending via Resend. Do not set this in production.

`RESEND_API_KEY` — get from [resend.com](https://resend.com) dashboard → API Keys.
For OAuth, each provider needs `CLIENT_ID` and `CLIENT_SECRET` from their dev console.
For S3/WAF, the standard `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_DEFAULT_REGION`.

---

## What Is Not Yet Active

- **Stripe billing** — code and migration complete, waiting on company registration
  for production keys. Once you have keys, see `DEPLOYMENT.md` → "Adding Stripe Later".
- **WAF/Cloudflare blocking** — code complete; requires each customer to configure
  their WAF IP set or Cloudflare zone in the Settings page.
