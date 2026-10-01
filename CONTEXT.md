# Product Context - Clew

> **Product name:** Clew
> **Codename (repo):** abuse

This file is the narrative companion to [README.md](README.md). README is the
reference doc: what exists, how to run it, the exact schema/routes/architecture
as built today. This file is the "why": product reasoning, history, judgment
calls made along the way, known gaps, and design decisions worth remembering.
If the two ever disagree on a factual claim (a route, a column, a file path),
trust README, it's the one meant to be kept in lockstep with the code.

---

## What Clew Is

Clew is a B2B SaaS product that monitors a company's own API traffic for abuse
and attack patterns using a multi-agent AI detection engine, and can
automatically block malicious IPs via AWS WAF or Cloudflare.

**Zero-integration positioning:** the customer gives Clew read-only S3 access
to their existing AWS API Gateway or ALB access logs. No code changes, no
proxy sitting in the request path, no SDK to install. Clew polls S3 every 15
minutes, runs detection, and surfaces findings in a web dashboard. This
positioning is deliberate and non-negotiable: anything that requires the
customer to change their own code or add a runtime dependency is a much
harder sell to a CTO who is already stretched thin, and kills deals before
they start.

**Target customers:** Seed and Series A/B SaaS companies and SMBs with public
APIs and no dedicated security team. The decision maker is a CTO or VP
Engineering, not a security specialist, so the product needs to explain
itself in business terms (cost prevented, not just "27 SQLi attempts
blocked").

**Key differentiators:**
- Zero integration burden (S3 access only, nothing touches the request path)
- AI detection validated on published academic datasets (CICIDS2017 is the
  one actually wired into the offline eval harness; CTU-13 and CSIC are
  referenced in marketing copy but are not in this repo)
- A cost-justified ROI metric shown in the dashboard ("$X prevented this
  month"), because a CTO evaluating a security tool wants a number to put in
  front of their own boss, not just a threat count

**Stack, briefly:** FastAPI (Python) backend, Next.js (App Router, TypeScript)
frontend, PostgreSQL for relational data, Redis for the detection engine's own
memory plus rate limiting and caching, Celery and Celery Beat for background
and scheduled work (log ingestion, alerts, metering, purges). Deployed today
as one EC2 instance with PM2 process management, no Kubernetes, no managed
database, see Key Design Decisions below for why.

**The detection engine, briefly:** six agents run in parallel on every
15-minute batch of ingested logs, each scoring a different signal: `VolumeAgent`
(DoS/floods), `TemporalAgent` (bot timing patterns), `AuthAgent` (credential
stuffing/brute force), `PayloadAgent` (SQLi/XSS/path traversal), `SequenceAgent`
(endpoint enumeration), and `GeoIPAgent` (geographic anomalies). A seventh,
`KnowledgeAgent`, runs passively, matching known threat signatures across a
customer's history but emitting no score of its own, so docs sometimes call it
"6 active + 1 passive." A `MetaAgentOrchestrator` fuses the 6 active scores into
one confidence value and severity band (weighted vote, with an XGBoost
stacking model that comes online once an organization has enough labeled
verdict history). Full technical detail is in README.md under "The Detection
Engine"; this paragraph exists so this file doesn't require README.md to
answer a basic "what does the product actually detect" question.

---

## Tiers and Pricing

Rewritten 2026-09-20 after the tier-restructuring rollout shipped, prices
updated 2026-10-01. Prices are marked **EARLY ACCESS**, valid until 2028.
Annual billing is a flat 50% off the monthly price, paid upfront for the
year, non-refundable beyond the standard 72-hour remorse window on the
first charge (same rule as monthly, see "Refunds and cancellations" in the
legal pages). This is a deliberate retention and cash-flow choice: an
annual signup is a locked-in year of revenue even if the customer stops
using the product, which matters more than usual while the company is
pre-funding. Currency is auto-detected from the
browser's timezone (India, Kolkata, gets INR; everywhere else gets USD), with
a manual toggle on the pricing page and in the dashboard's billing section.

| Tier | Marketing name | Internal tier code | Price | Blocking | Retention | Volume cap |
|---|---|---|---|---|---|---|
| Free | Starter | `free` | $0, no card, no trial, no expiry | None | 7 days | 2M calls/mo |
| Basic | Basic | `starter` | $49 / Rs.1,999 per month | Manual only (dashboard button) | 30 days | 10M calls/mo |
| Growth | Growth | `growth` | $129 / Rs.4,999 per month | Manual + automatic (WAF/Cloudflare) | 3 months | 50M calls/mo |
| Pro | Pro | `pro` | $249 / Rs.9,999 per month | Manual + automatic | 1 year | 200M calls/mo |
| Enterprise | Enterprise | `enterprise` | Custom | Manual + automatic + inline proxy (future) | Unlimited | Beyond 200M calls/mo, uncapped |
| Clew Audit | n/a | n/a | $599 / Rs.49,999 one-time | n/a | n/a | n/a |

**Clew Audit** is not a subscription tier, it's a one-time, sales-assisted
product: a full retrospective scan of a prospect's available log history,
sold as a standalone way to show value before any subscription commitment.
It isn't self-serve checkout, the pricing page routes it to a `mailto:`
link, not Razorpay/Stripe.

The internal tier code intentionally still says `starter` for the Basic
plan and reuses `free` for the permanent no-card plan: both predate the
marketing rename, and keeping them unchanged avoided touching billing
logic, Razorpay Plan ID env vars, and every tier-gated constant across the
backend. Don't rename these strings without a real reason, `api/tiers.py`'s
`MANUAL_BLOCK_TIERS`/`AUTO_BLOCK_TIERS`/`CALL_VOLUME_CAPS`/`RETENTION_DAYS`/
`LTM_TTL_DAYS` and `billing.py`'s `_TIER_RANK` all key off these exact values.

Free (Starter) is what every self-serve signup lands on directly: no trial,
no countdown, no card ever. The only way onto a paid tier as a trial is a
promo code, which grants a 30-day trial of Growth (not an extended free
tier, since the free tier never expires anyway). If that trial ends unpaid,
the org reverts to free Starter and keeps scanning within the free cap,
it is not a lockout.

Basic is the "you can see it and act on it yourself" tier: monitoring,
email alerts, and manual one-click blocking, but no unattended automatic
blocking. A threat is detected, the customer is alerted, and a human decides
whether to block. Growth and Pro add automatic unattended blocking on top of
that, gated behind a one-time Blocking Subscription Agreement acceptance
since it's an active security action, not passive monitoring. Pro's
differentiator over Growth is not blocking (both get it) but deeper control
over the detection engine itself: tunable confidence and custom thresholds.
That tuning is agreed and specified but **not built**, see `TODO.md` under
"Detection engine". Growth and above also get Groq-generated threat
explanations.

**What's real as of 2026-10-01, and what still isn't:** call-volume metering
and tiered retention purge both run. "Threat explanations" is now a real
Groq-backed LLM call for Growth and above, not the old rule-based template,
with a fail-soft fallback to the template if Groq is slow, erroring, or
unconfigured. Two gaps from the original 2026-09-02 audit remain unbuilt and
are still sold on the pricing page: Pro's "lower detection confidence
threshold" and "custom thresholds". Nothing in the engine is tier-aware on
confidence, every agent's constant is global. Those two are the agreed
differentiator for Pro over Growth (both tiers get automatic blocking, so
Pro's value has to come from tuning the engine), so they matter commercially,
but they are not MVP. See `TODO.md` under "Detection engine".

---

## Current Build Status (2026-10-01)

The MVP is functionally complete. One planning document, `TODO.md`, holds
everything still to do, grouped by topic rather than ordered, plus the
Razorpay go-live checklist at the top. The phase-by-phase build history that
used to live in a separate file has been folded into Product History below.

What's live and working:
- Registration, email verification, login, MFA (TOTP + backup codes),
  password reset, session management, account deletion (DPDP-compliant
  soft-delete then 30-day hard-purge)
- Multi-tenant organizations with role-based access (owner/admin/viewer),
  team invites, and ownership transfer
- S3 log ingestion (API Gateway and ALB formats) via **cross-account
  `sts:AssumeRole`** with a per-org External ID, the 6-agent detection engine,
  verdict generation, IP intelligence, dashboard
- Groq-backed threat explanations for Growth and above, fail-soft to the
  rule-based template
- Email alerts (severity-threshold gated, excluded on the free tier) and a
  delivery log
- WAF and Cloudflare IP blocking, through the same cross-account role,
  verified end to end against real AWS resources
- Call-volume metering with 80% and 100% soft-limit emails and a dashboard
  banner, plus tiered data retention enforced by a daily purge task
- Guided onboarding (per organization, dismissible, re-openable) and
  plan selection carried from the landing page through registration into
  checkout
- A public `/docs` page, a newsletter double opt-in via Resend Audiences on a
  separate sending subdomain, and legal pages carrying the real registered
  entity details
- Security hardening: CSP headers, Turnstile CAPTCHA, login lockout,
  Redis-backed rate limiting shared across workers, webhook replay guards,
  Fernet-encrypted Cloudflare tokens

What's built but not switched on yet:
- **Razorpay** is code complete and verified against a mocked client, but the
  six Plan objects do not exist and every `RAZORPAY_*` env var is blank,
  pending the founder's bank and KYC approval. Every code path degrades to a
  clean 503. The two-step upgrade checkout (a one-time Orders API proration
  charge, then the subscription mandate) has never run against a live or
  sandbox account, and is the highest-risk untested path in the product.
- **Stripe billing (USD)**: all code written, migration applied, blocked on
  live API keys which are themselves blocked on company registration. Non-INR
  visitors see an India-only panel rather than a checkout that cannot
  complete. India-first is a market strategy, not a stopgap.

Known open items are no longer listed here. They live in `TODO.md`, grouped
by topic, so this file does not drift out of sync with them again.

---

## Product History

A condensed, phase-by-phase account of how the product got to its current
state, including the judgment calls and reversals along the way. This is
the kind of context that doesn't belong in README (which describes the
current state, not how it was arrived at) but matters if you're ever
wondering "why is this built this way instead of the more obvious way."

**Phase 1, foundation.** Distributed locking so Beat firing again mid-run
doesn't double-process a backlog; source-key based verdict deduplication so
re-processing the same S3 object never creates a duplicate detection; a
7-day historical window on first connection instead of reading a customer's
entire log history; automatic log-format detection (API Gateway vs ALB) with
a clean abort if the wrong format is configured; a login brute-force lockout
separate from the general rate limiter; a `scan_runs` table so a clean batch
has evidence it was actually scanned, instead of writing a fake
"severity=none" verdict row. An independent review after this phase found
and fixed 6 real bugs, most notably that two engine memory fields were never
being persisted to Redis at all, silently making an entire adaptive-threshold
feature dead code in production while an offline test harness masked the gap
by reusing one in-process object across calls.

**Phase 2, multi-tenancy.** The original schema was purely per-login: one
`Client` row held both the login and all the S3/billing/blocking config.
This phase split that into `Client` (login identity only) and `Organization`
(the tenant, owning everything else), connected by `OrganizationMember` for
role-based team access. This was a full rekey of every foreign key in the
system (`client_id` to `org_id` across verdicts, ip_memory, alerts_sent,
scan_runs, and the entire detection engine's own internal parameter naming).
OAuth/social sign-in, which had existed in the codebase from before any of
this work began, was removed entirely once it became clear it was never an
actually-wanted feature, not a design decision made during this project.

**Phase 3, onboarding.** The registration flow's shape was genuinely
reconsidered three times in the same day before landing on its final form:
collect company name at signup and create the login, organization, and
membership atomically in one transaction. The alternative (create only a
login at signup, prompt for a company name later on first dashboard visit)
was built, then reversed, because a company email realistically belongs to
exactly one employer, so the extra step buys nothing for the common case.
The one-org-per-login assumption is a deliberate simplification. A
freelancer or consultant managing several clients' organizations from one
personal email is a real, known future case, and the schema already
supports it (`OrganizationMember` is genuinely many-to-many), it's just not
exposed as a signup-time flow yet.

**Phase 4, product UX.** Dashboard states for "no S3 configured yet" and
"configured but no data yet," a scanning-in-progress banner, IP
intelligence enriched with geography and ASN ownership, a full verdict
detail page (per-agent score breakdown, a raw log sample, an AI-analysis
section gated by tier). The "raw log sample" is worth understanding as a
known approximation: the detection engine scores a whole batch of records
together, there is no true per-line suspicion score to sort by, so the
sample is a best-effort selection of lines matching the verdict's IP and
endpoint, padded out with the batch's first lines if there aren't enough.

**Phase 5, email deliverability.** Dedicated from-addresses and reply-to
targets per email category (alerts, billing, team) on a `email.` subdomain,
separate from the root domain, so a bounce or spam complaint on
transactional mail never touches the root domain's own sending reputation.

**Phase 6, billing.** Stripe was already fully built before this phase; this
phase added Razorpay alongside it (not instead of it), plus real promo code
redemption, a trial-expiry job that reverts an unpaid trial to the free
tier, and the blocking Terms of Service acceptance gate. A genuinely
interesting implementation detail: Razorpay upgrades take effect
immediately (cancel the old subscription, start the new one now), but
downgrades are deferred to the end of the current billing cycle so a
customer doesn't lose access to something they already paid for this month.
A customer's very first payment method uses a different rule again, a
calendar-anchor (start on the 1st of the next month if signing up after the
15th, otherwise start immediately), since there's no existing cycle to
respect yet.

**Phase 7, security and account lifecycle.** Content-Security-Policy
headers, Turnstile CAPTCHA extended to forgot-password (it already existed
on registration), and DPDP-compliant account deletion. The account deletion
design resolved a real open question: when an organization's *owner*
deletes their own account, does the whole organization disappear with them,
even if other admins or viewers are still active members? The answer landed
on yes, unconditionally, the confirm dialog just warns the owner about it,
because building a forced ownership-transfer-or-block flow was judged not
worth the complexity for an MVP. A follow-up request the same day did add a
voluntary "make this admin the new owner" action, so an owner who wants to
hand off the organization before leaving can do so; nothing forces them to.

**Phase 8, operations and repo hygiene.** Originally scoped as nightly
database backups plus three layers of uptime/health monitoring
(UptimeRobot, a Cronitor heartbeat, and Sentry). Sentry was cut to post-MVP
from the start. Partway through, the backup and monitoring work was itself
reconsidered and pushed to post-MVP too: there's no real customer data yet
that a backup would be protecting, and a monitoring setup done "properly"
(a real customer-facing status page, not just a free-tier stopgap) needs an
actual audience to justify it, which doesn't exist before a first real
client. What did ship this phase: pinning two previously-transitive
dependencies (`pydantic`, `cryptography`) that the product's own code
imports directly, fixing a handful of stale doc references (a renamed
`middleware.ts` to `proxy.ts`, a PM2 config file that already existed
instead of the docs telling you to hand-write a second copy), and, in a
same-day follow-up, discovering and fixing a real local-development bug: the
API's entry point loaded its `.env.local` developer overrides *after*
importing modules that had already read the un-overridden production values
into fixed constants, which silently broke local testing (wrong database
password, CAPTCHA permanently failing) for anyone using the override file as
intended.

**The 2026-09-20 audit rollout.** A full pass over every claim the marketing
and legal pages made, checked against the code, which found that copy had
outrun implementation in several places. The worst was the Privacy Policy
naming Groq as an active subprocessor doing LLM analysis when Groq was not
wired into production at all, a legal document describing a data-sharing
relationship that did not exist. Also found and fixed: a payment-verification
handler that trusted a client-supplied tier (so a paid Starter payload could
be replayed as Pro), the backend having no concept of the Enterprise tier it
was selling, plaintext Cloudflare API tokens contradicting an "encrypted at
rest" claim, and a rate limiter whose counters lived per-process and reset on
every deploy. The same rollout built real usage metering and tiered retention,
and restructured the tiers so Starter became permanently free.

**The 2026-09-30 and 2026-10-01 completion phases.** Cross-account IAM roles
replacing the shared credential (see Key Design Decisions below), verified
against real AWS including a deliberate negative test confirming the External
ID condition is actually enforced rather than decorative. Groq wired into the
production pipeline with a fail-soft fallback. Guided onboarding and plan
selection carried from the landing page into checkout. A public docs page.
Legal pages filled in with the real registered entity. A newsletter on a
separate sending subdomain so marketing complaints cannot damage the
reputation of the domain that delivers security alerts.

Two bugs from these phases are worth remembering because they are the same
class. First, the KnowledgeAgent was learning per-customer IP reputation and
then silently discarding all of it, because two fields were missing from the
Redis serialization dictionary, the exact same failure that had already
happened once before with two different fields. The offline eval harness
cannot catch this class of bug at all, because it reuses one in-process
memory object and never round-trips through Redis. Second, blocking was
code-complete and architecturally correct but had never once run against a
real WAF IP set, only against mocked boto3 clients, which is why a dedicated
verification phase was added rather than trusting the unit tests.

---

## Known Limitations and Documented Gaps

- **Automatic blocking can run without the Blocking Subscription Agreement
  being accepted.** The acceptance gate is checked on both manual-block
  routes and at Razorpay checkout, but not in the automatic trigger path
  (`process_logs.py`/`push_blocks.py`). A Growth or Pro org that configures a
  WAF IP set or Cloudflare zone but never explicitly accepts the agreement
  still gets unattended blocking. Real legal exposure, not just a code gap,
  tracked as `[MVP]` in `TODO.md` under "Blocking."
- **No on/off switch for automatic blocking, despite marketing implying one
  exists.** The landing page's "How It Works" copy says Growth/Pro customers
  "can enable automatic WAF blocking with one setting." No such setting
  exists: the moment a WAF IP set or Cloudflare zone is configured, unattended
  blocking is live with no explicit opt-in, and one false positive (shared NAT
  gateway, corporate proxy, mobile carrier) can block real users nobody chose
  to block. Tracked as `[MVP]` in `TODO.md` under "Blocking."
- **`GeoIPAgent` has never been exercised at scale.** The archived CICIDS
  evaluation F1 numbers are a 5-agent result; `home_country` only became
  settable in the 2026-09-20 rollout, making the off-country detection branch
  reachable but still unvalidated against real multi-country traffic. Treat
  geography-driven verdicts as directionally useful, not independently proven.
- **Distributed low-and-slow attacks.** The engine's per-IP focus pass needs
  20 or more requests from a single IP within one 15-minute poll to catch
  attacks that a wide detection window would otherwise dilute. Thousands of
  distinct low-volume IPs (for example, a large botnet doing credential
  stuffing at one attempt per IP) can currently evade both detection passes.
  Cross-IP behavioral clustering to catch this is a Pro-tier roadmap item,
  not built yet.
- **No cross-email account switcher.** The one-org-per-login registration
  flow is a deliberate simplification, not a technical ceiling, the schema
  already supports one login belonging to multiple organizations.
- **Usage metering and tiered retention are live.** Call volume is counted
  per org per month against `CALL_VOLUME_CAPS`, with 80% and 100% soft-limit
  emails and a dashboard banner. Scanning is never cut off at the cap, it is
  a soft limit by design. A daily task hard-deletes data past each tier's
  retention window (7 days free, 30 Basic, 3 months Growth, 1 year Pro,
  unlimited Enterprise).
- **The verdict "raw log sample" is an approximation**, not a real per-line
  suspicion score, see Phase 4 above.
- **`detection/scripts/ablation_study.py`** is 300+ lines of research
  tooling (per-agent contribution measurement across four academic
  datasets) that predates this product's commercial build. It's
  intentionally kept in the repo as a labeled research artifact, not
  something anyone is expected to run as part of the product, and three of
  its four reference datasets aren't even present in this repo.
- **CONTEXT.md and README.md are both living documents**, not frozen specs.
  `TODO.md` is fully gitignored and never appears in `git status`, it's a
  private planning document, not part of the shipped product.

---

## Key Design Decisions

- **Zero integration, always.** No inline proxy, no SDK, no client code
  changes, ever, for the core product. This is the whole positioning; an
  inline proxy is listed as a possible Enterprise-tier future option
  precisely because it's a different, heavier product decision, not a
  natural evolution of the core one.
- **Organization-centric multi-tenancy over per-login config.** A `Client`
  is just a person who can log in; an `Organization` owns everything else.
  This makes team access, billing, and role-based permissions coherent
  without a second parallel identity system.
- **One EC2 instance, no Kubernetes, no managed database yet.** Sufficient
  for the first several dozen customers at the traffic volumes this product
  actually sees. RDS with automated snapshots is the explicitly-planned next
  step once monthly recurring revenue justifies the cost, not before.
- **LTM (the detection engine's long-term memory) lives in Redis, not
  Postgres.** It's high-write, engine-internal state (baseline rates,
  timing history, per-agent history), not relational data anyone queries
  directly, so a simple Redis key per organization is a better fit than a
  relational table.
- **httpOnly cookies, not localStorage, for auth tokens.** This closes off
  an entire class of XSS-based token theft; the tradeoff is the frontend
  needs an Edge-middleware refresh dance instead of just reading a token
  out of JS-visible storage.
- **Currency from browser timezone, not IP geolocation.** India gets INR,
  everywhere else gets USD, with a manual override always available. Simple,
  no third-party geolocation dependency, good enough for a pricing-page
  default.
- **Razorpay first, Stripe second, not Stripe first with Razorpay as an
  afterthought.** The product is India-first by market strategy, and
  Stripe was already fully built from before this project's work began;
  Razorpay was the piece that needed building to serve the actual first
  target market.
- **Cross-account IAM roles, not a shared Clew-owned key pair.** Each
  customer creates an IAM role in their own AWS account trusting Clew's
  account, conditioned on a per-org, server-generated External ID. Clew calls
  `sts:AssumeRole` and works with one-hour temporary credentials. The same
  role carries both S3 read and WAF blocking permissions, so there is one
  trust relationship, not two. This replaced the original design (one shared
  IAM user with a long-lived key pair accessing every customer's bucket),
  which was rebuilt in 2026-09-30's phase 2 because the blast radius of a
  single leaked key was every customer at once, with no expiry, no rotation
  path, no customer-side revocation, and no protection against the confused-
  deputy attack that the External ID specifically closes. The ambient-
  credential path still exists as a fallback for any org without a role ARN,
  and gets removed once every org has migrated.

---

## Where to Look for What

- **README.md**: the reference doc. Architecture, exact database schema,
  every API route, how to run everything locally, how to deploy to
  production, day-to-day operational commands.
- **TODO.md** (gitignored): everything still to do, grouped by topic, in no
  particular order, plus the Razorpay go-live checklist at the top (the one
  piece of active, non-future work). There is no separate build-history file
  anymore, the phase-by-phase account above is the durable record of that.
- **DESIGN_SYSTEM.md** (inside `frontend/`): the frontend's visual rules,
  read this before touching any CSS or adding new UI.
- **This file**: why things are built the way they are, the history behind
  non-obvious decisions, and known gaps worth remembering before assuming
  something is a bug.
