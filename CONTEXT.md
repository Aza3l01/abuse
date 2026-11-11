# Product Context - Clew

> **Product name:** Clew
> **Codename (repo):** abuse
> **Last verified against the code:** 2026-11-11 (the day it went live), Alembic head `a8d4f1c6b293`

This file is the narrative companion to [README.md](README.md). README is the reference doc: how the code is
organised, the schema, the routes, how to run and deploy it. This file is the "why": what the product is, how the
pieces fit, the judgment calls made along the way, the traps already hit, and the known gaps. It is written to be
read on its own (for example pasted into a chat with an AI assistant) so it repeats the essential facts. If the two
files ever disagree on a factual claim (a route, a column, a file path), trust README and the code.

---

## What Clew Is

Clew is a B2B SaaS product that monitors a company's own API traffic for abuse and attack patterns using a
multi-agent detection engine, explains what it found in plain language, and can block malicious IPs through AWS WAF
or Cloudflare.

**Zero-integration positioning:** the customer gives Clew read-only access to the S3 bucket that already holds their
AWS API Gateway or ALB access logs. No code changes, no proxy in the request path, no SDK. Clew polls S3 every 15
minutes, runs detection, and shows findings in a web dashboard. This is deliberate and not negotiable for the core
product: anything that makes the customer change their own code or add a runtime dependency is a much harder sell to
a CTO who is already stretched thin.

**Target customers:** SaaS companies and SMBs with public APIs and no dedicated security team. The decision maker is
a CTO or VP Engineering, not a security specialist, so the product explains itself in business terms (an estimated
"cost prevented", not just "27 SQLi attempts").

**Key differentiators:**
- Zero integration burden (S3 read access only, nothing touches the request path).
- Detection checked on published academic data. CICIDS2017 is the dataset wired into the offline evaluation harness
  (`detection/evaluate.py`); CTU-13 and CSIC are mentioned in marketing copy but are not in the repo.
- A cost-justified ROI figure in the dashboard, because a CTO wants a number to show their own manager.

**Current state (2026-11-11):** the MVP (Phases 1 to 15 of the build plan) is deployed and live on one EC2 host. The
marketing site, the customer dashboard, the API and the internal ops panel are all served over HTTPS. Customer
payments are not live yet: the Razorpay account is not approved for live charges and no live webhook exists, so the
payment code is tested only against a fake client and Razorpay test mode. Database backups, the live payment test and
the legal review are still open. The open work list is in `TODO.md` (gitignored, private).

---

## Stack and Architecture

**Backend:** FastAPI (Python; 3.11 in the local venv, 3.12 on the server), SQLAlchemy 2, Alembic, PostgreSQL 16.
**Background work:** Celery worker and Celery Beat on Redis 7 (log ingestion, alerts, blocking, billing, metering,
purges, daily metrics). **Frontend:** Next.js 16 (App Router, TypeScript), Tailwind with CSS variables and no
component library. **Auth:** httpOnly JWT cookies, bcrypt, TOTP MFA, Cloudflare Turnstile. **Email:** Resend.
**Payments:** Razorpay Orders (USD and INR); Stripe code exists but is unused. **LLM:** Groq (OpenAI compatible API,
default model `openai/gpt-oss-20b`), used only to write explanations. **Analytics and errors:** PostHog (EU).
**Uptime:** Better Stack monitors and heartbeats. **GeoIP:** MaxMind GeoLite2 files, downloaded per server.

**Deployment today:** one EC2 instance. PM2 runs four processes: `clew-api` (uvicorn, 127.0.0.1:8000),
`clew-frontend` (`next start`, port 3000), `clew-worker` (Celery, concurrency 4) and `clew-beat` (Celery Beat, exactly
one instance). Postgres and Redis are on the same machine. nginx terminates TLS (certbot) and is the only thing
facing the internet. There is no staging environment, no Kubernetes and no managed database.

**Hosts** (one Next.js process serves all front hosts; `frontend/src/proxy.ts` looks at the Host header):

| Host | Serves |
|---|---|
| `www.clewsec.com` | Marketing site, canonical. `/api/` proxied by nginx |
| `clewsec.com` | 301 to `www` |
| `dashboard.clewsec.com` | The app at the root path (no `/dashboard` prefix; the code lives in `app/dashboard/*`, old `/dashboard/...` URLs get a 308). `/api/` proxied by nginx |
| `api.clewsec.com` | FastAPI directly, for webhooks and the external API |
| `internal.clewsec.com` | The staff ops panel. nginx proxies only `/api/internal/` here, and `/internal` routes return 404 on every other host |

The browser calls the API same-origin at `/api/*`, which nginx maps to FastAPI. That mapping stays in nginx and is
never a Next.js rewrite in production, because a rewrite hides the client IP from the rate limiter (which keys on the
rightmost `X-Forwarded-For` entry). Auth cookies are host-only (`COOKIE_DOMAIN` blank); `LEGACY_COOKIE_DOMAIN` only
deletes the old `.clewsec.com` cookies. The one cross-host cookie is `clew_consent` (analytics consent), via
`NEXT_PUBLIC_COOKIE_DOMAIN=.clewsec.com`.

**Scheduled tasks** (Celery Beat, UTC, `workers/beat.py`):

| Task | When | What |
|---|---|---|
| `poll_all_clients` | every 15 min | One `process_logs` per org with S3 configured (skips deleted and paused orgs) |
| `send_trial_reminders` | 09:00 | 5 day and 2 day pilot reminders; moves an unpaid expired pilot to Starter |
| `purge_deleted_accounts` | 03:00 | Hard-deletes orgs and clients soft-deleted 30 or more days ago |
| `purge_expired_data` | 04:00 | Tiered retention purge |
| `reset_monthly_counters` | 00:00 on the 1st | Resets call-volume counters |
| `billing_cycle` | 19:00 (00:30 IST) | Bill engine: issue bills, enforce cancels and downgrades |
| `metrics_snapshot` | 19:30 | Daily business metrics for the ops panel |
| `reconcile_payments` | 19:45 | Compares Razorpay payments with local rows, reports only |

---

## The Detection Engine

Six agents run on every batch of ingested logs, each scoring a different signal: `VolumeAgent` (floods, Isolation
Forest), `TemporalAgent` (bot timing, FFT and CUSUM), `AuthAgent` (credential stuffing and brute force),
`PayloadAgent` (SQLi, XSS, path traversal), `SequenceAgent` (endpoint enumeration) and `GeoIPAgent` (geographic
anomalies). A seventh, `KnowledgeAgent`, is passive: it matches known threat signatures against a customer's history
and emits no score, so docs sometimes say "6 active + 1 passive". `MetaAgentOrchestrator` fuses the six scores into
one confidence value and a severity band, using a weighted vote plus an XGBoost stacking model that comes online
once an organization has enough labeled verdict history.

`process_logs` (one task per org per poll) runs three passes: **Pass A** mixed-IP window batches through the full
engine (writes the engine's long-term memory), **Pass B** a per-IP focus pass for IPs with at least 20 requests in the
poll (reads memory, never writes it), and **Pass C** cross-IP clustering for low-volume distributed attacks (Pro and
Enterprise only, alert only, never auto-blocks).

- **The verdict is decided by rules, never by the LLM.** The LLM (`LLM_ENABLED` is the kill switch) only writes the 2
  to 4 sentence customer-facing explanation afterwards, for Growth and above, with a template fallback on error,
  kill switch or the per-org monthly cap (Growth 5,000, Pro 25,000).
- **Optional reputation boost:** with `ABUSEIPDB_API_KEY` set, a hit for the busiest flagged IP adds 0.08 to the
  confidence of a batch an agent already flagged. It never creates a detection alone. Off while the key is blank.
- **Long-term memory lives in Redis** (`clew:ltm:{org_id}`), so deploys and worker restarts do not lose learned
  baselines. Its TTL depends on the tier. Any new memory field must be added to both `_dump_ltm()` and `_load_ltm()`
  in `detection/engine/memory/product_memory.py` with a round-trip test, because fields have been silently dropped
  twice and the offline harness cannot catch it (it reuses one in-process object and never round-trips through Redis).
- **Pro and Enterprise can tune detection** (attack and block confidence thresholds, per-agent and per-endpoint
  minimums; validated by `api/detection_config.py`). Growth and above can run automatic blocking in dry run mode
  (`auto_block_dry_run`), which records `would_have_blocked_at` on verdicts without touching WAF or Cloudflare.
- **Log record schema.** The ingestion layer normalises API Gateway and ALB lines into `LogRecord`
  (`detection/schemas/models.py`): `timestamp`, `ip`, `method`, `endpoint`, `status`, `response_size`, `latency`,
  `user_agent`, plus `endpoint_template`, `session_id`, `geo_context`, `tenant_home_country` and `org_id`. The label
  fields (`label`, `attack_category`, `is_attack`) are only filled in the offline research harness. Each production
  line also carries a `source_key` used for verdict deduplication.

---

## Tiers and Pricing

Internal tier codes equal the marketing names: `starter` (the permanent free plan), `basic`, `growth`, `pro`,
`enterprise`. They were renamed together (migration `f4b9d2a6c718`) so the two vocabularies cannot drift; do not
invent a different internal name. Everything keys off the constants in `api/tiers.py`
(`MANUAL_BLOCK_TIERS`, `AUTO_BLOCK_TIERS`, `CUSTOM_THRESHOLD_TIERS`, `CALL_VOLUME_CAPS`, `RETENTION_DAYS`,
`LTM_TTL_DAYS`, `LLM_EXPLANATION_TIERS`, `LLM_CALL_CAPS`, `PLAN_PRICES`).

| Tier | Price (USD / INR, per month, plus GST in India) | Blocking | Retention | Volume cap |
|---|---|---|---|---|
| `starter` | $0, no card, no trial, no expiry | None | 7 days | 2M calls/mo |
| `basic` | $49 / Rs.1,999 | Manual only (dashboard button) | 30 days | 10M |
| `growth` | $129 / Rs.4,999 | Manual and automatic | 90 days | 50M |
| `pro` | $249 / Rs.9,999 | Manual and automatic, custom detection thresholds, cross-IP clustering | 365 days | 200M |
| `enterprise` | Custom | All of the above (inline proxy is a possible future option) | Unlimited | Uncapped |

- Annual billing is 6 times the monthly price (a 50 percent discount, paid upfront), non-refundable after the 72 hour
  window that follows the first payment. USD annual: Basic 294, Growth 774, Pro 1,494. INR annual: 11,994, 29,994,
  59,994.
- **Currency:** the checkout picks INR for billing country India and USD otherwise. The pricing page default comes
  from the browser timezone (Kolkata means INR), with a manual toggle. An organization's currency locks when its first
  payment is captured.
- **Clew Audit** (one-time retrospective scan, $599 / Rs.49,999) is sales-assisted, not self-serve, and its pricing
  callout is hidden until it is ready to sell. README has the delivery runbook.
- **Starter** is where every self-serve signup lands: no trial, no countdown, scanning continues within the free cap.
  The only way to a paid tier without paying is a pilot code.
- **Pilot codes** (admin generated in the ops panel, single use) give a 30 day Growth pilot with no card. At the end an
  unpaid pilot drops to Starter. A pilot can pay for any plan at any time through the normal checkout.
- Growth and above also get automatic unattended blocking, behind a one-time Blocking Subscription Agreement and a
  per-org opt-in (`auto_block_enabled`, which cannot be switched on until the agreement is accepted).
- **Soft limits:** call volume is metered per org per month; 80 percent and 100 percent emails and a dashboard banner
  fire, but scanning never stops at the cap. A daily purge deletes data older than the tier's retention window.

---

## Billing Model

Bill, then pay. Razorpay Orders only, no Razorpay subscriptions or Plans (UPI autopay caps below the annual prices,
and the old subscription flow had upgrade-ordering and webhook-race bugs).

- The server prices every purchase from `PLAN_PRICES` (currency, tier, period) and `api/billing_rules.py`; the client
  never sends an amount or tier. `create-order` writes a `payments` row and a Razorpay order; the browser callback and
  the webhook both call `apply_captured_payment` (`api/billing_payments.py`), which is row-locked and idempotent, so a
  payment is applied exactly once whichever arrives first. Webhooks are HMAC verified and replay guarded.
- **First purchase:** pay the full plan price at upgrade, service starts at once. Paid on day 1 to 15 of a month: the
  next bill is issued on the 1st of the next month. Day 16 or later: the 1st of the month after. No prorating.
- **Every later period:** a bill is issued on the 1st, due the 20th, and the plan stays active until the 1st of the
  next month. Unpaid by then: the org drops to Starter, the unpaid bill stays open, and **Restore** lets the customer
  pay all open bills plus the new period in one checkout. A 30 day retention grace follows any downgrade, and the
  org's existing blocks stay in place and can be removed.
- **Upgrade** pays the price difference now (same period type) or the full annual price for a switch to annual;
  **downgrade** and **cancel** take effect at the next bill or the end of the paid period.
- **Refund:** full, within 72 hours of the first captured payment; the org drops to Starter.
- All calendar rules are evaluated in IST. `billing_cycle` runs at 19:00 UTC, which is 00:30 IST.
- Emails come from `billing@email.clewsec.com`: bill ready, due in 3 days, cancel warning, plan cancelled. No emailed
  invoice; the receipt page in the dashboard is the record. No GST tax invoices yet (needs a GST registration).
- **Referrals** run on a credit ledger (`credits` table, `api/referrals.py`). A referred org gets its first bill after its
  first payment covered by a free-month credit. Its referrer earns a credit that only ever reduces the referrer's own
  bills (never cash), starts pending, becomes available once the referee's first payment has stood for the 72 hour
  refund window, and is revoked by a refund inside it. A referrer who vests more than 3 credits in 30 days has the
  extras held until staff approve them in the ops panel. `REFERRAL_CREDIT_PCT` (default 100) sets the credit size; no
  exchange rate is ever used.
- Payments and bills are financial records and survive account deletion (the org id becomes NULL with a name and email
  snapshot on the row).

---

## Product Areas Worth Knowing

- **Accounts and tenancy.** A `Client` is a login identity only; an `Organization` owns everything else (S3, blocking,
  billing, detection data), joined through `OrganizationMember` (owner, admin, viewer). The org is re-derived from a
  live membership row on every request, never trusted from the JWT. Registration creates the login, org and
  membership in one transaction. A login can belong to several orgs (the schema supports it; the signup flow creates
  one). Account deletion is a DPDP style soft delete, hard-purged 30 days later; an owner's deletion deletes the whole
  organization.
- **Customer AWS access.** Each org gets a server-generated External ID; the customer creates an IAM role that trusts
  Clew's account with that External ID condition, and Clew calls `sts:AssumeRole` for one hour credentials. The same
  role carries S3 read and, if wanted, WAF permissions. An org with no role falls back to Clew's own AWS key; this
  fallback is a known risk (see Known Limitations).
- **Scanning pause.** An organization's team can pause scanning; polling skips it, manual block and unblock and the
  retention purge continue.
- **Internal ops panel** (`internal.clewsec.com`, `/api/internal/*`, `api/routes/internal.py`, `api/staff_*.py`).
  Staff only: its own table (`staff_users`), cookie (`clew_staff`), signing key, password plus TOTP login, 60 minute
  absolute session, and every action is written to an audit log with a reason. It can search accounts, read raw data,
  mark or void bills, extend a period or a pilot, pause a downgrade, reinstate, generate pilot codes, manage referral
  credits, and shows system health, the audit log and the business metrics (`metrics_daily`, with an INR combined view
  using `METRICS_INR_PER_USD`). Staff users are created only on the server with `scripts/create_staff_user.py`.
- **Analytics and monitoring.** PostHog (EU) for product events, with a consent banner and `clew_consent` cookie, and for
  exceptions from the API, Celery and the frontend. Better Stack for uptime and two heartbeats (`HEARTBEAT_URL` pinged by
  `poll_all_clients`, `BILLING_HEARTBEAT_URL` by `billing_cycle`). API errors return a `correlation_id` (also sent as the
  `x-correlation-id` response header) so support can find the log line.
- **Newsletter and legal.** Double opt-in newsletter through Resend Audiences on a separate sending subdomain. Legal
  pages (terms, privacy, DPA, subscription agreement, refund policy) carry the registered entity details. A public
  `/docs` page explains the product.
- **Security basics.** CSP with nonces, Turnstile on register, login and forgot-password, login lockout
  per email and IP, Redis-backed rate limiting shared across workers, webhook replay guards, Fernet-encrypted Cloudflare
  tokens and TOTP secrets.

---

## Product History (condensed)

How the product got here, including reversals, for anyone asking "why is it built this way".

- **Foundation.** Distributed locking so Beat firing during a long run cannot double-process; source-key based verdict
  deduplication; a 7 day window on first connection; log format auto-detection; a `scan_runs` table so a clean batch
  has evidence it was scanned. A review found that two memory fields were never persisted to Redis, which silently
  disabled an adaptive-threshold feature while the offline harness masked it.
- **Multi-tenancy.** The original schema put login and tenant config on one `Client` row. It was split into `Client`
  and `Organization` and every foreign key was rekeyed from `client_id` to `org_id`. OAuth sign-in, which predated this
  work, was removed.
- **Onboarding.** Registration collects the company name and creates login, org and membership atomically. The
  "create the org later" variant was built and reversed.
- **Billing.** Stripe came first and Razorpay (India first) was added, first as subscriptions with immediate upgrades,
  deferred downgrades and calendar anchors. That design was replaced in late 2026 by Orders, monthly bills and the
  rules above, because subscriptions cannot carry the annual prices on UPI or cards in India.
- **The 2026-09-20 audit.** Marketing and legal copy was checked against the code. Found and fixed: the Privacy Policy
  named an LLM subprocessor that was not wired in, a payment verification handler that trusted a client-supplied tier,
  no Enterprise tier in the backend, plaintext Cloudflare tokens contradicting "encrypted at rest", and a rate limiter
  whose counters reset on every deploy.
- **Cross-account IAM roles** replaced one shared IAM user with a long-lived key, verified against real AWS including a
  negative test that the External ID condition is enforced.
- **Host split and the ops panel (2026-11).** Marketing, app, API and ops panel got separate hosts; billing was rebuilt
  on Orders; the staff panel, combined metrics, backup scripts, detection tuning, analytics, referral credits, a
  scanning pause and a full QA pass followed; the fixes from that pass shipped with the go-live.
- **Go-live (2026-11-11).** Phases 2 to 14 were deployed together in one commit with one database migration run, no
  staging, and no pre-deploy database backup (a deliberate choice, so the only rollback is the previous commit).
- **Two bug classes worth remembering.** Memory fields dropped from Redis serialization (twice), and blocking code that
  was architecturally correct but had never run against a real WAF IP set, only mocked clients.

---

## Known Limitations and Documented Gaps

- **AWS ambient-credential fallback is a confused deputy risk.** An org that has an S3 bucket but no role ARN is read
  with Clew's own AWS key (`aws_session_for_org()` in `api/aws.py`). The bucket name is only format-checked, so a tenant
  could name another customer's bucket if that customer used the legacy bucket policy. The fix is to remove the
  fallback; it needs a decision and a check that no live org depends on it.
- **No live payments yet.** See "Current state". No real charge, refund or webhook has been seen.
- **No database backups on the server yet.** The scripts exist (`scripts/backup_postgres.sh`, `restore_postgres.sh`);
  installing them and a restore drill are open.
- **`GeoIPAgent` has never been exercised at scale** on real multi-country traffic. The archived CICIDS F1 numbers are
  a 5 agent result. Treat geography-driven verdicts as directionally useful.
- **Distributed low-and-slow attacks.** Pass B needs 20 or more requests from one IP in a poll. Pass C (Pro and
  Enterprise) groups low-volume IPs but is alert only and not validated on real distributed traffic. A botnet at one
  request per IP per poll can evade the other passes.
- **The verdict "raw log sample" is an approximation:** the engine scores a batch, not individual lines, so the sample
  is a best-effort selection of lines matching the verdict's IP and endpoint.
- **GeoIP files are refreshed by hand** each month (no cron) and the worker must be restarted afterwards.
- **`METRICS_INR_PER_USD`** is read by the code (`api/metrics.py`, `workers/tasks/metrics_snapshot.py`) but is no
  longer documented in `.env.example`; if it is missing, the combined INR figures in the ops panel are unavailable.
- **`detection/scripts/ablation_study.py`** is research tooling that predates the product, kept as a labeled artifact;
  three of its four reference datasets are not in the repo.
- **Unverified:** Groq pricing for `openai/gpt-oss-20b`, live AbuseIPDB lookups, and detection quality on real traffic
  (offline tests use stubs and the CICIDS data).

---

## Key Design Decisions and Gotchas

- **Zero integration, always** for the core product. An inline proxy is only a possible Enterprise option.
- **Organization-centric multi-tenancy** over per-login config, so team access, billing and roles stay coherent.
- **Rules decide, the LLM explains.** The verdict never depends on model output.
- **Long-term memory in Redis, not Postgres**: high-write, engine-internal state nobody queries relationally.
- **httpOnly cookies, not localStorage**, for tokens; the cost is a refresh step in `proxy.ts` and `apiFetch()`.
- **Razorpay first, Stripe optional later.** The Stripe routes and columns are kept but unused.
- **One role, two capability sets** for customer AWS access (S3 read and optional WAF), not two trust relationships.
- **Same-origin `/api` through nginx**, never a Next.js rewrite (it hides the client IP from the rate limiter).
- **Gotchas already paid for:**
  - Every Celery task module must be listed in `include=[...]` in `workers/celery_app.py`; a missing one fails silently.
    After adding one, read the worker startup `[tasks]` list. Celery task lines go to stderr (`pm2 logs ... --err`).
  - FastAPI with `from __future__ import annotations` and a slowapi `@limiter.limit` decorator turns body parameters
    into required query parameters (422 on every request). Do not add that import to a route file that uses the limiter.
    This is the "FastAPI body parameter note" that `api/routes/internal.py` refers to.
  - `db/session.py`, `api/main.py` and the Celery app load `.env` then `.env.local` with override, so a local
    `.env.local` must never be copied to the server. Do not `source .env` in a shell (special characters).
  - Migrations: run `alembic heads` for the real `down_revision`; there should be exactly one head.
  - A uvicorn started without `--reload` keeps serving old code after an edit.
  - `NEXT_PUBLIC_*` variables are baked in at `npm run build`; change them, rebuild.
  - Do not use an em dash anywhere in the repo (frontend copy, docs, comments, chat replies); see
    `frontend/DESIGN_SYSTEM.md`.

---

## Where to Look for What

- **README.md**: reference. Structure, schema, every route, running locally, deploying, backups, the Clew Audit runbook.
- **TODO.md** (gitignored, private): what is open (Part 1), future work (Part 2), reference and decisions (Part 3) and
  the archive of finished phases (Part 4). Item and phase numbers are stable.
- **frontend/DESIGN_SYSTEM.md**: the visual rules (monospace, no gradients, no rounded corners, no emoji, no em dash).
  Read it before touching CSS or UI copy.
- **frontend/AGENTS.md** and **frontend/CLAUDE.md**: notes for coding agents working on the frontend (Next.js 16).
- **.github/copilot-instructions.md**: the working rules for AI agents in this repo (ask before editing code).
- **This file**: why things are built the way they are and the traps to avoid.
