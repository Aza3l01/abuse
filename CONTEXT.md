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

---

## Tiers and Pricing

All prices are marked **EARLY ACCESS**, valid until 2027, and every tier
starts with a no-card trial (7 days self-serve, 30 days with a valid promo
code). Annual billing is 2 months free (about 17% off). Currency is
auto-detected from the browser's timezone (India, Kolkata, gets INR;
everywhere else gets USD), with a manual toggle on the pricing page.

| Tier | Price | Blocking | History |
|---|---|---|---|
| Starter | $39 / Rs.2,999 per month | No | 90 days |
| Growth | $69 / Rs.4,999 per month | WAF + Cloudflare | 1 year |
| Pro | $129 / Rs.9,999 per month | WAF + Cloudflare, lower confidence threshold | 3 years |
| Enterprise | Custom | WAF + Cloudflare + inline proxy (future) | Unlimited |
| Clew Audit | $599 / Rs.49,999 one-time (early access) | n/a | n/a |

Starter is the "does it work" tier: monitoring and email alerts only, no
blocking. Growth and Pro add WAF/Cloudflare blocking, gated behind a one-time
blocking Terms of Service acceptance since it's an active security action,
not passive monitoring.

---

## Current Build Status (as of Phase 8, 2026-08-11)

Every MVP phase (1 through 8) in the project TODO is complete in the working
tree. **No commits have been made** across any of that work; committing is
the repo owner's call, not something done automatically session to session.
`git status` will show a large uncommitted diff against the last real commit,
that is expected, not a sign anything is broken.

What's actually live and working:
- Registration, email verification, login, MFA (TOTP + backup codes),
  password reset, session management, account deletion (DPDP-compliant
  soft-delete then 30-day hard-purge)
- Multi-tenant organizations with role-based access (owner/admin/viewer),
  team invites, and ownership transfer
- S3 log ingestion (API Gateway and ALB formats), the 6-agent detection
  engine, verdict generation, IP intelligence, dashboard
- Email alerts (severity-threshold gated) and a delivery log
- WAF and Cloudflare IP blocking, tier-gated and ToS-gated
- Razorpay billing (INR), fully wired end to end including webhooks,
  upgrades/downgrades, refunds, and promo code redemption
- Security hardening: CSP headers, Turnstile CAPTCHA on register and
  forgot-password, login lockout, rate limiting

What's built but not fully switched on yet:
- **Stripe billing (USD)**: all code is written and the DB migration is
  applied, but it's blocked on live API keys, which are themselves blocked
  on company registration. Razorpay is the live path for now; this product
  is India-first by design, not as a stopgap.
- **Razorpay itself** is code-complete but was, as of the last check-in,
  waiting on the founder's own Razorpay KYC/bank approval before real keys
  exist. Every code path degrades cleanly with blank keys (clean 503s, no
  crashes), so this was treated as a valid "done" state for the phase that
  built it.

What's explicitly deferred to post-MVP, and why: database backups, uptime
and worker health monitoring (UptimeRobot/Cronitor), an internal ops panel,
a staging environment, usage metering, webhook/Slack/PagerDuty alert
channels, a public customer-facing API, Groq-generated verdict explanations,
and Sentry exception tracking. None of these block signing a first real
client. The operations items in particular (backups, monitoring) were
originally scoped for MVP and then deliberately pushed to post-MVP once it
became clear there's no real customer data yet to protect and no audience
yet for a status page, revisit them when actually onboarding the first paying
client, not before.

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

---

## Known Limitations and Documented Gaps

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
- **Usage metering columns exist, nothing increments them.**
  `organizations.monthly_requests_processed` is on the schema (added ahead
  of time per the original checklist) but no code writes to it yet, and no
  tier is anywhere near a volume limit that would make this urgent.
- **The verdict "raw log sample" is an approximation**, not a real per-line
  suspicion score, see Phase 4 above.
- **`detection/scripts/ablation_study.py`** is 300+ lines of research
  tooling (per-agent contribution measurement across four academic
  datasets) that predates this product's commercial build. It's
  intentionally kept in the repo as a labeled research artifact, not
  something anyone is expected to run as part of the product, and three of
  its four reference datasets aren't even present in this repo.
- **CONTEXT.md and README.md are both gitignored-adjacent living documents**,
  not frozen specs. TODO.md itself is fully gitignored and never appears in
  `git status`, it's a private execution plan, not part of the shipped
  product.

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
- **One shared Clew-owned AWS IAM identity, not per-customer AWS keys.**
  Every customer's S3 bucket is accessed via one IAM user's credentials on
  the Clew side, with the customer granting bucket-level permissions to
  that one identity. A cross-account IAM role (so no long-lived key pair
  needs to exist at all) is an accepted, deliberate launch tradeoff, not an
  oversight, and is the explicit next step on the roadmap.

---

## Where to Look for What

- **README.md**: the reference doc. Architecture, exact database schema,
  every API route, how to run everything locally, how to deploy to
  production, day-to-day operational commands.
- **TODO.md** (gitignored, never appears in `git status`): the execution
  plan. Item numbers are stable and never renumbered, so a reference like
  "item 27" always means the same thing across the project's lifetime.
- **DESIGN_SYSTEM.md** (inside `frontend/`): the frontend's visual rules,
  read this before touching any CSS or adding new UI.
- **This file**: why things are built the way they are, the history behind
  non-obvious decisions, and known gaps worth remembering before assuming
  something is a bug.
