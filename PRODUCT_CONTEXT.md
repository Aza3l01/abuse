# Product Context — Clew

> **Product name:** Clew
> **Codename (repo):** abuse

---

## What Clew Is

B2B SaaS API abuse detection and blocking. Customers give Clew read-only S3 access
to their existing AWS API Gateway or ALB logs — no code changes, no proxy, no SDK.
Clew polls S3 every 15 minutes, runs a multi-agent AI detection engine, and surfaces
findings through a web dashboard. High-confidence threats can be automatically blocked
via AWS WAF or Cloudflare on paid tiers.

**Target customers:** Series A/B SaaS companies and SMBs with public APIs and no
dedicated security team. Decision maker is a CTO or VP Engineering.

**Key differentiators:**
- Zero integration burden (S3 access only, nothing touches the request path)
- AI detection validated on published academic datasets (CICIDS2017, CTU-13, CSIC)
- Cost-justified ROI metric shown in the dashboard ("$X prevented this month")

---

## Current Build Status

Everything listed below is **complete and working**. The only item that is code-complete
but not yet active is Stripe billing, which is waiting on company registration for
production API keys (approximately one week).

---

## Tiers

| Tier | Price | Blocking | History |
|---|---|---|---|
| Free | $0 | No | 7 days |
| Starter | $99 / ₹6,999 per month | No | 90 days |
| Growth | $249 / ₹14,999 per month | WAF + Cloudflare | 1 year |
| Pro | $449 / ₹29,999 per month | WAF + Cloudflare (lower threshold) | Unlimited |

Currency auto-detected from browser timezone. Manual toggle available.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Python 3.11 |
| Database | PostgreSQL 16 |
| Cache / queue broker | Redis 7 |
| Background jobs | Celery + Celery Beat |
| Frontend | Next.js 16 (App Router) |
| Styling | Tailwind CSS + CSS variables (no component library) |
| Auth | httpOnly JWT cookies + bcrypt + pyotp |
| Email | AWS SES |
| Billing | Stripe (code complete, keys pending) |
| Detection | Custom multi-agent engine (Python 3.11) |
| Blocking | AWS WAF v2 (boto3) + Cloudflare API |
| Process manager | PM2 (EC2 production) |
| Web server | Nginx |

---

## Repository Structure

```
abuse/
├── api/                    FastAPI backend
│   ├── main.py             App entry point, CORS, all routers registered
│   ├── deps.py             get_db(), get_current_client() dependencies
│   ├── auth_utils.py       Hashing, JWT, cookies, OTP, SES email
│   ├── limiter.py          Shared slowapi rate limiter
│   └── routes/
│       ├── auth.py         All auth endpoints
│       ├── clients.py      Client S3 + alert config
│       ├── verdicts.py     Detection results + manual blocking
│       ├── dashboard.py    Summary stats endpoint
│       ├── ips.py          IP intelligence table
│       └── billing.py      Stripe checkout + webhook
├── db/
│   ├── models.py           SQLAlchemy ORM (7 tables)
│   ├── session.py          Engine + SessionLocal
│   └── migrations/         3 Alembic migrations (initial, stripe, mfa_backup_codes)
├── engine/
│   ├── engine -> source    Symlink for import resolution
│   ├── schemas/models.py   LogRecord Pydantic model
│   └── source/
│       ├── agents/         7 detection agents
│       ├── coordinator/    MetaAgentOrchestrator
│       ├── memory/         SharedMemory + Redis-backed ProductSharedMemory
│       ├── pipeline/run.py run_pipeline() — Celery entry point
│       └── ingestion/      S3Reader, apigw_parser, alb_parser, normalizer
├── workers/
│   ├── celery_app.py       Celery app + config
│   ├── beat.py             poll_all_clients every 15 min
│   └── tasks/
│       ├── process_logs.py S3 -> detect -> verdicts + ip_memory
│       ├── send_alerts.py  SES alerts for high/critical
│       └── push_blocks.py  WAF + Cloudflare block/unblock
├── blocking/
│   ├── aws_waf.py          WAF IP set management
│   └── cloudflare.py       Cloudflare firewall rules
├── frontend/               Next.js 16
│   └── src/
│       ├── app/            All routes (marketing + dashboard)
│       ├── components/     UI components
│       ├── lib/api.ts      API_URL constant
│       └── middleware.ts   Edge auth gatekeeper
├── docker/
│   ├── docker-compose.yml  Local Postgres + Redis
│   ├── nginx.conf          Production Nginx config
│   └── ecosystem.config.js PM2 process definitions
├── DESIGN_SYSTEM.md        CSS variables, typography, component conventions
├── DEV_NOTES.md            Developer onboarding guide (zero to everything)
├── DEPLOYMENT.md           Step-by-step production server setup guide
└── NOTES.md                Product strategy and positioning notes
```

---

## All API Endpoints

### Auth (`/auth`)

| Method | Path | Description |
|---|---|---|
| POST | /auth/register | Create account |
| POST | /auth/verify-email | Submit OTP |
| POST | /auth/resend-verification | Re-send OTP |
| POST | /auth/login | Login → sets httpOnly cookies |
| POST | /auth/logout | Clear cookies, revoke session |
| POST | /auth/refresh | Silent token refresh |
| GET | /auth/me | Current client profile |
| POST | /auth/forgot-password | Request password reset OTP |
| POST | /auth/reset-password | Email + OTP + new password |
| GET | /auth/google | Start Google OAuth |
| GET | /auth/google/callback | Google callback |
| GET | /auth/github | Start GitHub OAuth |
| GET | /auth/github/callback | GitHub callback |
| GET | /auth/microsoft | Start Microsoft Entra OAuth |
| GET | /auth/microsoft/callback | Microsoft callback |
| POST | /auth/mfa/setup | Generate TOTP secret + QR URI |
| POST | /auth/mfa/verify | Confirm TOTP, enable MFA, get backup codes |
| POST | /auth/mfa/disable | Disable MFA |
| POST | /auth/login/mfa | Submit TOTP code during login challenge |
| GET | /auth/sessions | List active sessions |
| DELETE | /auth/sessions/{id} | Revoke one session |
| DELETE | /auth/sessions | Revoke all sessions |

### Other endpoints

| Method | Path | Description |
|---|---|---|
| GET | /clients/me | Client config |
| PATCH | /clients/me | Update client config |
| GET | /verdicts | Paginated verdicts |
| GET | /verdicts/{id} | Single verdict |
| POST | /verdicts/{id}/block | Manual block |
| POST | /verdicts/{id}/unblock | Manual unblock |
| GET | /dashboard/summary?days= | Stats + trend |
| GET | /ips | IP intelligence table |
| GET | /billing/status | Tier + subscription |
| POST | /billing/checkout | Create Stripe Checkout Session |
| POST | /billing/portal | Create Stripe Customer Portal Session |
| POST | /billing/webhook | Stripe webhook handler |
| GET | /health | `{"status": "ok"}` |

---

## Database Schema

### `clients`
One row per customer account. Key columns: `email`, `password_hash` (null for
OAuth-only), `company_name`, `s3_bucket`, `s3_prefix`, `log_format` (apigw/alb),
`aws_region`, `last_processed_key`, `tier` (free/starter/growth/pro),
`mfa_enabled`, `mfa_secret` (Fernet-encrypted), `stripe_customer_id`,
`stripe_subscription_id`, `tier_expires_at`, `alerts_enabled`, `alert_email`,
`waf_ip_set_id`, `cloudflare_zone_id`, `cloudflare_token`.

### `oauth_accounts`
Links a provider identity to a client. Unique on `(provider, provider_id)`.
Supports Google, GitHub, Microsoft. One client can have multiple OAuth accounts.

### `refresh_tokens`
One row per active browser session. Stored as SHA-256 hash. `revoked` bool for
instant invalidation. Powers "View and revoke sessions" in Settings.

### `verdicts`
One row per pipeline batch result. `ip`, `threat_type`, `severity`,
`confidence` (0-1), `agents_triggered` (JSON array), `explanation`, `blocked`,
`cost_prevented`.

### `ip_memory`
One row per `(client_id, ip)`. Updated on every detection run. Powers the IPs
dashboard page. `first_seen`, `last_seen`, `total_requests`, `threat_count`,
`risk_score`, `geo_country`.

### `alerts_sent`
Deduplication table for SES notifications. One row per `(verdict_id, channel)`.

### `mfa_backup_codes`
10 hashed single-use recovery codes per client.

**Migrations applied:** `c957d12130b9` → `b4e8f2a1c953` → `e3c1a7f920d4` (head)

---

## Detection Engine

### Seven agents

| Agent | Signal detected | Algorithm |
|---|---|---|
| VolumeAgent | DoS / DDoS / floods | Isolation Forest |
| TemporalAgent | Bot periodicity, off-hours | FFT + CUSUM |
| AuthAgent | Brute force, credential stuffing | Failed auth rate analysis |
| PayloadAgent | SQLi, XSS, path traversal | Pattern matching |
| SequenceAgent | Endpoint enumeration | Sequence analysis |
| GeoIPAgent | Geographic anomalies | Graph-based clustering |
| KnowledgeAgent | Cross-session threats | Known signature matching |

All 7 run in parallel. `MetaAgentOrchestrator` fuses results via weighted average
+ XGBoost stacking + conflict resolution rules.

### Severity bands
- ≥ 0.80 → critical
- ≥ 0.60 → high
- ≥ 0.40 → medium
- < 0.40 → low

### State persistence
LTM (baselines, IAT pools, agent history) persisted in Redis as
`clew:ltm:{client_id}`. Loaded at task start, flushed at task end. Survives
worker restarts and redeployments.

### Entry point
```python
from engine.pipeline.run import run_pipeline
verdict = run_pipeline(records=[...], client_id="uuid", redis_client=redis_conn)
```

---

## S3 Ingestion Pipeline

```
Celery Beat (every 15 min)
    poll_all_clients task
        → one process_logs task per client with s3_bucket configured
            → S3Reader: list objects since last_processed_key
            → Normalize: apigw_parser or alb_parser → List[dict]
            → run_pipeline() in 500-record batches
            → INSERT into verdicts, UPSERT into ip_memory
            → UPDATE client.last_processed_key
            → trigger send_alerts (high/critical)
            → trigger push_block (Growth/Pro, confidence >= 0.75)
```

---

## Frontend Pages

| Route | Notes |
|---|---|
| `/` | Marketing homepage: Hero, interactive CostCalculator, HowItWorks, Pricing, Footer |
| `/pricing` | Standalone pricing page |
| `/login` | Credentials + Google/GitHub/Microsoft OAuth |
| `/register` | Email + password + company name |
| `/verify-email` | 6-digit OTP, resend button |
| `/forgot-password` | Anti-enumeration — always shows neutral success message |
| `/reset-password` | Email + OTP + new password — logs in on success |
| `/dashboard` | Stats grid, 7/30d stacked bar chart, top IPs list, recent verdicts |
| `/dashboard/alerts` | Paginated verdict feed, filters (severity / IP / date), manual block |
| `/dashboard/ips` | IP intelligence table, sortable by risk score / request count |
| `/dashboard/settings` | S3 config, IAM policy guide, alert email, MFA, sessions, billing |
| 404 | Custom not-found page |
| Error boundary | Global error page |

**SEO:** OG metadata in `layout.tsx`. `/sitemap.xml` and `/robots.txt`
generated by Next.js server functions.

**Auth gatekeeper:** `middleware.ts` runs at the Edge on every request. Verifies
JWT with `jose` (Web Crypto API). Silent refresh on expiry. Redirect to `/login`
on auth failure.

---

## Auth System

- **Two-token system:** 15-min access token + 7-day refresh token, both in httpOnly
  cookies (inaccessible to JavaScript)
- **Token rotation:** each `/auth/refresh` call revokes the old token and issues a
  new pair
- **Password security:** SHA-256 pre-hash → bcrypt(rounds=12)
- **OAuth:** Google, GitHub, Microsoft Entra — supports linking multiple providers
  to one account, and linking to existing credentials account by email match
- **MFA:** TOTP (RFC 6238) via pyotp, secret Fernet-encrypted at rest, 10 backup codes
- **Rate limiting:** slowapi (IP-based) + manual Redis counters (email-based)

---

## Blocking Integrations

**AWS WAF v2** — customer creates an IP set in their own AWS account, grants Clew's
IAM role `wafv2:GetIPSet` + `wafv2:UpdateIPSet`, stores the IP set ARN in Settings.

**Cloudflare** — customer provides API token with Firewall Rules permission and
zone ID. Stored per-client in DB.

Both can be active simultaneously. Blocking threshold: confidence ≥ 0.75, tier ≥
growth.

---

## Billing (Stripe — code complete)

**Status:** All code is written. DB migration `b4e8f2a1c953` is applied. Blocked on
getting production Stripe API keys (company registration in progress, ~1 week).

**What's built:**
- `GET /billing/status` — current tier + subscription state
- `POST /billing/checkout` — create Stripe Checkout Session
- `POST /billing/portal` — create Stripe Customer Portal Session
- `POST /billing/webhook` — verify Stripe signature, handle subscription lifecycle events
- Webhook handles: `checkout.session.completed`, `customer.subscription.updated`,
  `customer.subscription.deleted`

**To activate:** obtain Stripe keys, create products + prices in Stripe dashboard,
configure webhook endpoint. See `DEPLOYMENT.md` → "Adding Stripe Later".

---

## Production Infrastructure

Single EC2 t3.small (Ubuntu 24.04). Self-hosted Postgres + Redis on the same instance.

**Four PM2 processes** (defined in `docker/ecosystem.config.js`):
- `clew-api` — Uvicorn, 2 workers, port 8000
- `clew-frontend` — Next.js `start`, port 3000
- `clew-worker` — Celery worker, concurrency 4
- `clew-beat` — Celery beat scheduler (exactly one instance)

**Nginx** (`docker/nginx.conf`) — two server blocks:
- `yourdomain.com` → Next.js :3000
- `api.yourdomain.com` → FastAPI :8000

Full production setup steps are in `DEPLOYMENT.md`.

---

## What Is Not Yet Active

| Item | Status | Blocker |
|---|---|---|
| Stripe billing | Code + migration complete | Stripe API keys (company registration ~1 week) |
| WAF/Cloudflare blocking | Code complete | Each customer must configure their own WAF/CF |
| EC2 production deploy | Not yet done | Stripe keys first, then deploy |
| OG image asset | Not created | Visual design work |

---

## Key Design Decisions

- **No inline proxy, no SDK, no client code changes.** Zero integration is the
  positioning — anything that requires a code change kills deals.
- **One EC2, no Kubernetes.** Sufficient for first 50 clients. Adds no operational
  complexity.
- **No component library.** Custom CSS-variable design system (see `DESIGN_SYSTEM.md`).
  Terminal aesthetic — monospace, no gradients, no rounded corners.
- **LTM in Redis, not PostgreSQL.** LTM is high-write internal engine state, not
  relational data. Redis with JSON serialisation is simpler and faster.
- **Stripe deferred but code-ready.** All billing code is live. First few customers
  can be invoiced manually until keys arrive.
- **httpOnly cookies, not localStorage.** Prevents the entire class of XSS token
  theft attacks.
- **Currency from timezone.** India → INR, everywhere else → USD. No geolocation API
  needed; pure timezone string matching.
