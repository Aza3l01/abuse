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
├── detection/                 <- AI detection engine
│   ├── schemas/models.py      <- LogRecord pydantic model
│   └── engine/                <- engine package; `from engine.xxx` imports resolve here
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
| `password_hash` | varchar | bcrypt hash |
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

### Orchestrator — `detection/engine/coordinator/meta_agent.py`

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

### Import path setup

`detection/engine/pipeline/run.py` inserts `detection/` onto `sys.path` at import
time, so `from engine.xxx` and `from schemas.models` resolve correctly regardless
of Celery's working directory.

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
| `/login` | Client | Email + password |
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
python -m pytest detection/engine/tests/ -v
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
For S3/WAF, use `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_DEFAULT_REGION`.

---

## What Is Not Yet Active

- **Razorpay billing** — to be built (Phase 6 in TODO.md). INR customers are the first target market.
- **Stripe billing** — code exists but keys are pending company registration. Implement after first INR clients.
- **WAF/Cloudflare blocking** — code complete; requires each customer to configure
  their WAF IP set or Cloudflare zone in the Settings page.

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

#### 7.1 Create ecosystem.config.js

```bash
nano /home/ubuntu/abuse/ecosystem.config.js
```

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

### Pushing Code Updates

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

---

### Upgrading the Server

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

---

### Testing Tiers Without Billing

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

### Adding Razorpay (INR — build first)

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

### Adding Stripe (USD — after company registration)

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
