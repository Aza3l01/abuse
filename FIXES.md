# FIXES.md

Manual QA pass driven through the browser against the local dev stack
(Postgres + Redis in Docker, `uvicorn api.main:app`, Celery worker, Celery beat,
`next dev`), 2026-10-01.

Everything below was reproduced by clicking through the real UI unless the entry
says otherwise. Findings already tracked in `TODO.md` (automatic blocking
bypassing the Blocking Subscription Agreement, the missing `auto_block_enabled`
toggle, Pro's unbuilt confidence/custom thresholds, Razorpay and Stripe not
being live, the fixed INR to USD rate in `CostCalculator.tsx`, the pre-existing
`react-hooks/set-state-in-effect` lint errors) are deliberately **not** repeated
here.

## Test data created

All throwaway data was removed at the end of the run. Nothing is left behind.

- `owner@clewqa.test` (org "Clew QA Org"), `admin@clewqa.test`,
  `viewer@clewqa.test`: created, exercised, then hard deleted from Postgres.
  The remaining rows in the local DB (`Clew Security`, `Test Co`,
  `jeff@clewsec.com`, `onboardtest+...@example.com`) pre-date this run and were
  not touched.
- Seeded verdict / ip_memory rows for the QA org only: removed with the org.
- Newsletter contact `qa-news-test@example.com` was created in the **real**
  Resend contact list by the double opt-in test and has been deleted again
  (confirmed `{"deleted": true}` from the Resend API).
- The API and Celery worker were started with `LOG_EMAILS=1` (env var only, no
  file edits) so throwaway registrations did not send real mail to fake
  inboxes.
- The QA org's `tier` column was flipped across `free` / `starter` / `growth` /
  `pro` in Postgres for the cross-tier section, as requested.

---

# Auth

## [Severity: Critical] Accepting a team invite as a new user always fails with a 500 (Fixed 2026-10-01)

- **Where**: `/accept-invite?token=...`, "Set password and accept" button.
  Backend `POST /org/invite/{token}/accept`.
- **Steps to reproduce**:
  1. Sign in as an org owner, go to Settings, Team Members.
  2. Invite an email address that has no existing Clew account.
  3. Open the invite link from the email in a clean browser profile.
  4. Type a password, click "Set password and accept".
- **Expected**: The account is created, the invite is marked accepted, the user
  lands on the dashboard.
- **Actual**: The request returns 500 and the page shows "Could not connect to
  the server. Try again." The server log shows
  `psycopg2.errors.NotNullViolation: null value in column "full_name" of
  relation "clients" violates not-null constraint`. Reproduced for both an
  admin invite and a viewer invite. The existing-account branch of the same
  endpoint works, so only brand new invitees are affected, which is the normal
  case. Team invitations are effectively non-functional.
- **Suspected file(s)**: `api/routes/org.py` (`accept_invite`, the `Client(...)`
  construction around line 598 never sets `full_name`), `db/models.py`
  (`Client.full_name` is `nullable=False`). Either collect a name on the
  accept-invite form or make the column nullable.

**Fix**: collected full name on the accept-invite form (user's choice over
making the column nullable). `AcceptInviteBody` gained `full_name`, required
and validated server-side when no account exists yet, passed into the new
`Client(...)`. Frontend `accept-invite/page.tsx` gained a Full Name field next
to Password in the new-account branch. Re-verified live: registered a
throwaway owner, invited a brand-new email, opened the real invite link, filled
in name + password, accept succeeded (landed on `/dashboard`, no 500),
confirmed `full_name` persisted in Postgres. Test rows deleted afterward.
`tsc --noEmit` clean, `python -c "import api.main"` clean (67 routes), worker
suite 3/3.

## [Severity: High] An invite link alone grants a full session for an existing account, with no password and no MFA (Fixed 2026-10-01)

- **Where**: `POST /org/invite/{token}/accept`, reached from `/accept-invite`.
- **Steps to reproduce**:
  1. Have an existing Clew account with TOTP MFA enabled.
  2. Create an unaccepted invite for that same email address.
  3. From a browser profile that has never logged in, POST the accept endpoint
     with an empty body (the page does this automatically when
     `account_exists` is true).
- **Expected**: The invitee is asked to sign in (and pass MFA) before being
  added to the organisation.
- **Actual**: The endpoint returns 200 and sets `access_token`, `refresh_token`
  and `last_org_id` cookies. `GET /auth/me` then returns the victim's full
  profile including every organisation they belong to. Verified directly: a
  session that had never authenticated ended up as `owner@clewqa.test` with MFA
  enabled on that account. Anyone who can read or forward the invite email gets
  a complete account takeover, not just org membership, and MFA is skipped.
- **Suspected file(s)**: `api/routes/org.py`, `accept_invite` calls
  `_issue_tokens(...)` unconditionally in the existing-account branch.

**Fix**: added `get_optional_client()` to `api/deps.py` (same as
`get_current_client` but returns `None` instead of raising on a missing or
invalid session). `accept_invite()` now takes that as a dependency; when the
invite's email already has an account, it requires the caller to already be
signed in as that exact account (401 if signed out, 403 if signed in as a
different account) before adding membership and minting tokens, instead of
trusting the invite token alone. The new-account branch is unaffected, since
that one already proves ownership via setting a new password. Frontend
`accept-invite/page.tsx` now calls `GET /auth/me` when `account_exists` is
true: if the signed-in email doesn't match the invite, it shows "Sign in to
accept" linking to `/login?next=/accept-invite?token=...` instead of an
auto-accept button. Verified live end to end: registered an account, enabled
TOTP MFA on it, invited that same email to a second organisation, then from a
signed-out session POSTed the accept endpoint directly, which now returns 401
instead of minting a session. Then went through the real flow (sign in with
password, pass the TOTP challenge, land back on `/accept-invite`, click
"Accept invitation"), which succeeded, the `OrganizationMember` row and
`invite.accepted_at` both persisted correctly in Postgres. Test accounts,
organisations, and invites cleaned up afterward. `npx tsc --noEmit` clean,
`python workers/tests/test_process_logs.py` still 3/3 passing.

## [Severity: High] Password reset signs the user straight in and bypasses MFA (Fixed 2026-10-01)

- **Where**: `/reset-password`, `POST /auth/reset-password`.
- **Steps to reproduce**:
  1. Enable TOTP MFA on an account and confirm that signing in normally returns
     `MFA_REQUIRED`.
  2. Use "Forgot password?", enter the emailed code and a new password.
- **Expected**: After a successful reset, the user is sent to the login screen
  and must still pass the second factor, or is at minimum challenged for TOTP.
- **Actual**: The reset endpoint issues session cookies directly and the browser
  lands on `/dashboard` fully authenticated. The TOTP challenge is never shown.
  Control of the mailbox alone therefore defeats MFA entirely.
- **Suspected file(s)**: `api/routes/auth.py`, `reset_password` calls
  `_issue_tokens(...)` without checking `client.mfa_enabled`.

**Fix**: `reset_password()` now checks `client.mfa_enabled` after validating
the code and setting the new password. If MFA is on, it returns the same
`{"code": "MFA_REQUIRED", "mfa_token": ...}` shape `/auth/login` already uses,
instead of calling `_issue_tokens`, so no session cookie is set until the
second factor is verified via the existing `/auth/login/mfa` endpoint.
Accounts without MFA are unaffected and still log in immediately on reset.
Frontend `reset-password/page.tsx` gained the same MFA step UI already used on
the login page (TOTP input, backup-code toggle, posts to `/auth/login/mfa`).
Verified live: registered an account, enabled TOTP MFA, reset its password via
the emailed code, confirmed the response was an MFA challenge with no cookie
set (`GET /clients/me` 401 before verifying), then confirmed entering the TOTP
code logged in successfully. Separately verified a non-MFA account's reset
still logs straight in as before, no regression. `npx tsc --noEmit` clean,
`python workers/tests/test_process_logs.py` still 3/3 passing.

## [Severity: Medium] Rate-limited login shows a generic "Sign in failed." and never explains the lockout (Fixed 2026-10-01)

- **Where**: `/login`, and every other slowapi-limited route.
- **Steps to reproduce**:
  1. Enter a wrong password on `/login` repeatedly (3 attempts was enough
     locally).
  2. Keep going, then try the **correct** password.
- **Expected**: A clear message such as "Too many attempts, try again in N
  minutes."
- **Actual**: The first two failures show "Invalid credentials." Every attempt
  after that, including the one with the correct password, shows
  "Sign in failed." with no explanation. Root cause: slowapi returns
  `429 {"error": "Rate limit exceeded: 10 per 15 minute"}` while the frontend
  reads `data.detail` and falls back to a generic string. Confirmed against the
  raw API response. The dedicated per-email lockout message never gets a chance
  to show because the IP limiter trips first, and the limit is IP based, so a
  shared office NAT would lock out every user behind it.
- **Suspected file(s)**: `api/limiter.py` (no custom 429 handler mapping to
  `detail`), `frontend/src/app/login/page.tsx`.

**Fix**: added a custom `RateLimitExceeded` exception handler in `api/main.py`
that returns `{"detail": "Too many attempts. Please wait a few minutes and
try again."}` (429), replacing slowapi's default `{"error": "..."}` shape.
Every frontend error path already reads `data.detail` and only falls back to
a generic string when that key is missing, so no frontend change was needed,
the shape mismatch was the entire bug. Verified live: hammered `POST
/auth/login` with a wrong password past both limits. The first 5 requests hit
the existing per-email lockout (`_check_email_rate`, which already returned a
proper `detail` message), the next 5 hit the per-IP slowapi limit
(`10/15minutes`) and returned `{"detail": "Too many attempts. Please wait a
few minutes and try again."}` instead of the old unmapped `{"error": ...}`.
Flushed the test's rate-limit/lockout Redis keys afterward. Backend imports
clean, `python workers/tests/test_process_logs.py` still 3/3 passing. The
separate IP-vs-email limiter-ordering question (a shared office NAT locking
out every user) is a product/infra tradeoff, not addressed here, out of scope
for "the error message is wrong".

## [Severity: Low] Invite tokens are stored in plaintext inside Redis rate-limiter keys (Fixed 2026-10-01)

- **Where**: Redis, keys of the form
  `LIMITS:LIMITER/127.0.0.1//org/invite/<RAW_TOKEN>/accept/10/1/hour`.
- **Steps to reproduce**:
  1. Open an invite link so `POST /org/invite/{token}/accept` is hit.
  2. Run `redis-cli keys '*'`.
- **Expected**: Invite tokens are only ever stored hashed, as they are in
  `org_invites.token_hash`.
- **Actual**: The raw token is embedded in the limiter key because the limiter
  keys on the full request path. Anyone with Redis read access can replay a
  pending invite (see the High finding above for why that matters).
- **Suspected file(s)**: `api/limiter.py`, `api/routes/org.py` (the limited
  route has the token in its path).

**Fix**: slowapi's `Limiter` defaults to `key_style="url"`, which uses the
resolved request path (path params substituted in, e.g. the raw token) to
scope every rate-limit key. Switched to `key_style="endpoint"`
(`api/limiter.py`), which scopes by the route function's `module.name`
instead, a stable, secret-free string, every route still gets its own
independent limit bucket exactly as before, just not keyed by anything in
the URL. Verified live: restarted the dev server (picked up via
`--reload`), hit `POST /org/invite/{token}/accept` with a test token, and
confirmed via `redis-cli keys '*'` that the token string appears nowhere in
Redis, the new key is `LIMITS:LIMITER/127.0.0.1/api.routes.org.accept_invite/10/1/hour`.
Cleaned up stale pre-fix keys (created earlier in this session, before the
fix) that still held raw tokens. `python workers/tests/test_process_logs.py`
still 3/3 passing.

---

# Onboarding

## [Severity: Medium] Onboarding steps tick themselves complete even when the connection test failed (Partially fixed 2026-10-01)

- **Where**: Guided onboarding panel, "Connect your log source" and
  "Set up blocking" rows.
- **Steps to reproduce**:
  1. Register a fresh account so the guided panel auto-opens.
  2. Open the log source wizard, enter a bucket that does not exist, pick a
     format and a region, click "Save & continue".
  3. Go back to the checklist.
- **Expected**: The step stays incomplete while `s3_status` is `error`.
- **Actual**: The step shows a filled checkbox, "Setup progress" advances, and
  the panel eventually says "Every step is complete. Click Finish setup below
  whenever you're ready." while the status line directly above it reads
  `Error: Bucket 'clew-qa-nonexistent-bucket-12345' not found in region
  'ap-south-1'`. The same happens for the blocking step: saving a bogus WAF IP
  set ticks the step even though `POST /settings/test-waf` returned an error.
  A customer is told setup is finished when nothing will ever scan.
- **Suspected file(s)**:
  `frontend/src/components/dashboard/OnboardingModal.tsx`
  (`const s3Done = !!(config?.s3_bucket && config?.log_format)` ignores
  `s3_status`; `blockingDone` likewise only checks that an id is present).

**Fix**: `s3Done` now also requires `config.s3_status !== "error"`, so the
"Connect your log source" step stays unticked (and the "NEXT" pointer stays
on it) while the last S3 connection test failed, using the `s3_status`/
`s3_status_message` fields the backend already persists on every save.
Verified live: registered a fresh account, ran the wizard with a nonexistent
bucket name through to "Save & continue", confirmed "Setup progress" stayed
at 0 of 2 and the checklist still showed the step with its "NEXT" badge and
the literal `Error: Bucket '...' not found...` message, not a tick. Test
account cleaned up afterward. `npx tsc --noEmit` clean.
**Not fixed**: the "Set up blocking" step (`blockingDone`). Unlike S3, WAF/
Cloudflare test results (`POST /settings/test-waf` / `test-cloudflare`) are
never persisted anywhere, Settings page only holds the last test result in
local React state, so `OnboardingModal` (a different, unmounted-at-that-time
component) has no server-side field to check, equivalent to `s3_status` does
not exist for blocking. Fixing this properly needs a schema change (a
persisted `waf_status`/`cloudflare_status` column plus updating both test
endpoints to write it), which is a bigger change than this one finding
justifies on its own; flagging here rather than silently leaving it half-done.

## [Severity: Medium] Wizard step 7 swallows the real validation error for a malformed role ARN (Fixed 2026-10-01)

- **Where**: Guided onboarding, `LogSourceWizard` step 7 of 8, "Save & test".
- **Steps to reproduce**:
  1. Reach step 7 of the log source wizard.
  2. Type `not-an-arn` and click "Save & test".
- **Expected**: The backend's ARN-shape validation message, so the user knows
  what is wrong with what they pasted.
- **Actual**: `PATCH /clients/me` returns 422 and the wizard shows only
  "Save failed." For contrast, a well-formed but non-existent ARN
  (`arn:aws:iam::999999999999:role/ClewQaNotARealRole`) surfaces the real AWS
  error correctly, so the inconsistency is only on the validation path.
- **Suspected file(s)**:
  `frontend/src/components/dashboard/LogSourceWizard.tsx` (the save handler
  does not read `detail` out of a 422 response).

**Fix**: added the same `extractErrorMessage()` helper already used in
`BlockedIpsTab.tsx` (pulls `detail[0].msg` out of a Pydantic 422 error array,
falling back to a generic message only when `detail` really isn't readable)
and used it in both of the wizard's save handlers (`saveBasicsAndContinue`
and `saveRoleAndTest`), which previously only handled the case where `detail`
was already a plain string. Verified live: ran the wizard through to step 7,
typed `not-an-arn`, clicked "Save & test", and the step now shows the real
backend message ("aws_role_arn must look like
arn:aws:iam::<12-digit-account-id>:role/<role-name>") instead of a generic
"Save failed." Test account cleaned up afterward. `npx tsc --noEmit` clean,
`python workers/tests/test_process_logs.py` still 3/3 passing.

## [Severity: Low] The onboarding panel polls `/clients/me` every 6 seconds forever, including while minimised (Fixed 2026-10-01)

- **Where**: Any dashboard page with the guided panel open or minimised.
- **Steps to reproduce**:
  1. Register a fresh account, leave the panel docked or minimised.
  2. Count requests to `:8000` for 30 seconds on an otherwise idle page.
- **Expected**: Polling stops, or backs off, when the panel is minimised.
- **Actual**: 5 `GET /clients/me` calls per 30 seconds, indefinitely, until the
  org is explicitly dismissed or completed. That is roughly 14,000 requests per
  day per open tab.
- **Suspected file(s)**:
  `frontend/src/components/dashboard/OnboardingModal.tsx` (`POLL_MS = 6000`;
  the effect only bails when `stage === "hidden"`).

**Fix**: the poll interval now multiplies by 5 (30s instead of 6s) while
`stage === "minimized"`, and the effect returns early (no interval at all)
once `config.onboarding_completed_at` is set, since there's nothing left to
poll for by then. Docked/active panel keeps the original 6s interval so a
just-saved step still ticks off promptly. Verified live: registered a fresh
account, minimized the panel, and counted 0 `GET /clients/me` requests over
the next 16 seconds (previously would have been 2 to 3 at the old 6s
interval). Test account cleaned up afterward. `npx tsc --noEmit` clean,
`python workers/tests/test_process_logs.py` still 3/3 passing.

---

# Dashboard

## [Severity: Critical] An invalid IP in "Block an IP manually" crashes the whole IPs page (Fixed 2026-10-01)

- **Where**: `/dashboard/ips`, Blocked tab, "Block an IP manually" form.
- **Steps to reproduce**:
  1. Go to `/dashboard/ips`, open the Blocked tab.
  2. Click "Block an IP manually".
  3. Type `not-an-ip` in the IP address field and click "Block IP".
- **Expected**: An inline validation message such as "Enter a valid public IP
  address."
- **Actual**: `POST /verdicts/manual-block` returns 422 whose `detail` is an
  array of Pydantic error objects. The frontend assigns that array into a
  string-typed error state and React throws
  `Objects are not valid as a React child (found: object with keys {type, loc,
  msg, input})`. The error boundary replaces the entire page with
  "SOMETHING WENT WRONG / An unexpected error occurred." and the user has to
  reload. Screenshot captured during the run. The same class of bug was already
  fixed once in `TeamMembers.tsx` but not here. Private, loopback and reserved
  addresses (`10.0.0.5`, `127.0.0.1`) hit the same 422 path and will crash the
  page too.
- **Suspected file(s)**:
  `frontend/src/components/dashboard/BlockedIpsTab.tsx` (the manual block
  submit handler), mirroring the existing fix in `TeamMembers.tsx`.

**Fix**: added an `extractErrorMessage()` helper in `BlockedIpsTab.tsx` that
returns the string `detail` as-is, or pulls the first Pydantic error object's
`msg` out of an array `detail` (stripping the "Value error, " prefix Pydantic
adds for custom validators), falling back to a generic message only if neither
shape matches. Covers both the malformed-input case ("not-an-ip") and the
private/loopback/reserved case (`10.0.0.5`, `127.0.0.1`) since both come back
as the same `detail` array shape. `tsc --noEmit` clean.

## [Severity: High] The Verdicts tab shows Block / Unblock to every tier and every role (Fixed 2026-10-01)

- **Where**: `/dashboard/alerts`, Verdicts tab, Actions column.
- **Steps to reproduce**:
  1. Put an org on the free `free` tier.
  2. Open `/dashboard/alerts` as the owner and click "Block" on any verdict.
  3. Separately, sign in as a `viewer` of a Pro-tier org and open the same tab.
- **Expected**: Blocking is hidden entirely for the free Starter tier (it has no
  blocking at all) and hidden for viewers (documented RBAC says block and
  unblock are hidden for viewers). This is exactly what the verdict **detail**
  page already does.
- **Actual**: Every verdict row shows "Block" (or "Unblock") regardless of tier
  or role. On free tier the click produces
  `403 Forbidden` and a raw `window.alert("Blocking requires an active paid
  plan.")`. A viewer sees the same buttons. Only the backend stops it.
  Secondary issue: the error is a native browser alert, which is both a poor
  experience and outside the design system.
- **Suspected file(s)**:
  `frontend/src/components/dashboard/VerdictsTab.tsx` (no tier or role gate,
  unlike `frontend/src/app/dashboard/verdicts/[id]/page.tsx` which gates
  correctly), same pattern in
  `frontend/src/components/dashboard/BlockedIpsTab.tsx`.

**Fix**: both tabs now receive `role` and `tier` from their
parent page (`dashboard/alerts/page.tsx`, `dashboard/ips/page.tsx`), already
fetched via the existing `/clients/me` call, same source the Settings page
uses. `VerdictsTab` hides the Block/Unblock button per row unless
`role` is owner/admin AND (the verdict is already blocked, so a downgraded org
can still unblock, or `tier` is in the same `MANUAL_BLOCK_TIERS` list the
backend and the detail page use). `BlockedIpsTab`'s "Block an IP manually"
section is now gated the same way; its Unblock button stays role-only gated,
matching the backend (`/ips/{ip}/unblock` has no tier check). Also replaced
`VerdictsTab`'s raw `window.alert(...)` on a 403 with an inline error message
above the table, matching the design system (secondary issue). Verified live:
seeded a verdict and a pre-existing blocked IP for a free-tier org. As owner,
Block was hidden on Verdicts and "Block an IP manually" was hidden on the
Blocked tab, while the pre-existing Unblock button remained available.
Upgrading the same org to `pro` made Block and "Block an IP manually"
reappear for the owner (regression check). Invited a second account as
`viewer` to the pro-tier org: neither Block/Unblock nor the manual-block form
appeared anywhere, regardless of tier. Test org/accounts/verdicts cleaned up
afterward. `npx tsc --noEmit` clean, no em dashes introduced.

## [Severity: High] The docked onboarding panel covers the data tables and makes the Actions column unclickable (Fixed 2026-10-01)

- **Where**: `/dashboard`, `/dashboard/alerts`, `/dashboard/ips` while the
  guided onboarding panel is docked (which is the default for every new
  account).
- **Steps to reproduce**:
  1. Register a fresh account so the panel auto-opens.
  2. Seed or wait for at least one verdict.
  3. Go to `/dashboard/alerts` and try to click "Block" on the first row.
- **Expected**: The table fits the reserved content width, or scrolls
  horizontally within its own container.
- **Actual**: The table is 853px wide inside a 664px container with
  `overflow-x: visible`, so it spills under the fixed 380px panel
  (`position: fixed; z-index: 95`). Playwright reports
  `<div>…</div> intercepts pointer events` and `document.elementFromPoint` on
  the Block button returns the onboarding panel. The Severity, Confidence,
  Blocked and Actions columns are visually clipped and physically unclickable.
  The page has no horizontal scrollbar either (`document.scrollWidth` equals
  `clientWidth`), so the overflow is simply lost. The Overview page's "Recent
  threats" table has the same problem. Minimising the panel fixes it, but a
  brand new customer sees the broken state first.
- **Suspected file(s)**: `frontend/src/app/dashboard/layout.tsx` /
  `DashboardContentShell` margin reservation,
  `frontend/src/components/dashboard/VerdictsTab.tsx`,
  `frontend/src/components/dashboard/AllIpsTab.tsx`,
  `frontend/src/app/dashboard/page.tsx` (table wrappers need
  `overflow-x: auto`).

**Fix**: added `overflowX: "auto"` plus a `minWidth` on the `<table>` itself
(760px for Verdicts and Recent threats, 900px for All IPs, 600px for Blocked
IPs) to each table's own bordered wrapper div in `VerdictsTab.tsx`,
`AllIpsTab.tsx`, `BlockedIpsTab.tsx`, and `dashboard/page.tsx`'s Recent threats
table. The table no longer gets compressed to the container's width (which is
what was letting it spill out and under the panel); instead the container
itself scrolls horizontally when narrower than the table's minimum width.
`DashboardContentShell`'s margin reservation itself was already correct and
didn't need changing, the bug was purely the tables having nowhere to
overflow to. Verified live: registered a fresh account (onboarding panel
docked by default), seeded a verdict on a `pro`-tier org, confirmed the table
container now reports `scrollWidth (760) > clientWidth (529)` with
`overflow-x: auto` computed, and that clicking "Block" actually reaches the
backend (`POST /verdicts/{id}/block` 200 in the API log) instead of hitting
the onboarding panel underneath. Test account and data cleaned up afterward.
`npx tsc --noEmit` clean, `python workers/tests/test_process_logs.py` still
3/3 passing.

## [Severity: Medium] "Block this IP" gives no feedback at all, and a failed block is never surfaced (Fixed 2026-10-01)

- **Where**: `/dashboard/verdicts/[id]`, "Block this IP" button (Growth tier).
- **Steps to reproduce**:
  1. On a Growth-tier org with a WAF IP set configured, open a verdict detail
     page and click "Block this IP".
- **Expected**: A busy state, then either a "Blocked" state or a visible error.
- **Actual**: Nothing changes. The button text stays "Block this IP", there is
  no spinner, no toast and no error. `POST /verdicts/{id}/block` returns 200 and
  the page immediately refetches, but the actual work happens asynchronously in
  `push_block`, which in this run failed with
  `AWSAccessError: Clew could not assume the IAM role...` and went into a retry
  loop. The customer has no way to know the block did not happen; `blocked`
  stays `false` forever and the UI never says why.
- **Suspected file(s)**:
  `frontend/src/app/dashboard/verdicts/[id]/page.tsx`,
  `workers/tasks/push_blocks.py` (no surfaced failure state on the verdict).

**Fix**: `push_blocks.py` already persisted a per-integration
`waf_block_error`/`cloudflare_block_error` on `IpMemory` for the Blocked IPs
tab, the verdict detail page just never read it. Added both fields to
`VerdictDetailOut` (`GET /verdicts/{id}`), sourced from the same `IpMemory`
row. `handleBlock()` now waits ~2.5s after a successful `POST .../block`
(enough for the Celery task to run locally), refetches the verdict, and if
it's still not `blocked`, shows the real `waf_block_error`/
`cloudflare_block_error` text inline instead of the button just going quiet.
The 403 (no paid plan) case also moved from a raw `alert()` to the same
inline paragraph, consistent with the design system. Verified live: seeded a
pro-tier org with a bogus WAF IP set ID and a verdict, clicked "Block this
IP", and after the wait the page displayed the real AWS error ("An error
occurred (AccessDeniedException) when calling the GetIPSet operation...")
instead of nothing happening. Test data cleaned up afterward. `npx tsc
--noEmit` clean, backend imports clean, `python
workers/tests/test_process_logs.py` still 3/3 passing.

## [Severity: Medium] A 500 from the verdict endpoint is reported to the user as "Verdict not found." (Fixed 2026-10-01)

- **Where**: `/dashboard/verdicts/[id]`.
- **Steps to reproduce**:
  1. Make `GET /verdicts/{id}` return a 500 (during this run it was triggered by
     an `agent_scores` payload that did not match `AgentScoreOut`).
  2. Open the verdict detail page.
- **Expected**: An error state that distinguishes "this does not exist" from
  "something broke", ideally with something a support ticket can reference.
- **Actual**: The page renders "Verdict not found." for any non-OK response,
  including a 500. Because the 500 escapes `CORSMiddleware`, the browser also
  logs a misleading CORS error, which sends anyone debugging it down the wrong
  path.
- **Suspected file(s)**:
  `frontend/src/app/dashboard/verdicts/[id]/page.tsx` (treat `res.status === 404`
  separately from other failures).

**Fix**: the fetch handler now checks `res.status === 404` explicitly for
"Verdict not found.", any other non-OK status gets "Something went wrong
loading this verdict. Try again, or contact support if it keeps happening.",
and a genuine network/fetch failure (the `catch`) gets "Could not connect to
the server. Try again." Three distinct messages instead of one. Verified
live: seeded a verdict with a malformed `agent_scores` payload that fails
`AgentScoreOut` validation, triggering a real response-validation 500, and
confirmed the page no longer says "Verdict not found." (it showed "Could not
connect to the server." because, as this finding already noted, the 500
response itself never reaches the browser as a readable HTTP response, it's
blocked by CORS at the network layer before `fetch` even resolves a status,
which `apiFetch`'s `catch` branch now maps to a distinct, non-misleading
message). The CORS-obscuring-arbitrary-500s behavior itself is a separate,
deeper FastAPI/Starlette middleware-ordering issue (unhandled exceptions
bypass `CORSMiddleware`'s header injection), not something fixable from the
frontend and out of scope for "the error message is wrong", not addressed
here. Test data cleaned up afterward. `npx tsc --noEmit` clean,
`python workers/tests/test_process_logs.py` still 3/3 passing.

## [Severity: Low] "Recent threats" on the Overview is sorted by severity, not recency (Fixed 2026-10-01)

- **Where**: `/dashboard`, "Recent threats" panel.
- **Steps to reproduce**: Have verdicts of mixed severity and age, then look at
  the panel.
- **Expected**: Under a heading that says "Recent", newest first.
- **Actual**: Rows came back in the order Oct 1 04:35 PM (critical), Oct 1
  11:35 AM (critical), Oct 1 02:35 PM (high), Sep 27 (high), Sep 30 (medium),
  Sep 29 (low). A four-day-old high sits above a one-day-old medium. The sort is
  the documented severity-then-timestamp default from `verdicts.py`, but it does
  not match what the panel title promises.
- **Suspected file(s)**: `frontend/src/app/dashboard/page.tsx` (pass an explicit
  time sort), or rename the panel.

**Fix**: added a `sort: Literal["severity", "recent"] = "severity"` query
param to `GET /verdicts` (default unchanged, so the Alerts tab's
severity-first feed is untouched). `sort=recent` orders by
`Verdict.timestamp.desc()` only. The Overview page now requests
`/verdicts?limit=10&sort=recent` for its "Recent threats" panel. (The
route's docstring also incorrectly claimed the default was already
"timestamp DESC", corrected to describe the actual severity-then-timestamp
behavior.) Verified live: seeded verdicts at 1 hour, 30 minutes, 2 days, and
4 days old with critical/medium/low/high severities respectively, and
confirmed `GET /verdicts?limit=10&sort=recent` now returns them in strict
newest-first order regardless of severity. Test data cleaned up afterward.
`npx tsc --noEmit` clean, backend imports clean, `python
workers/tests/test_process_logs.py` still 3/3 passing.

## [Severity: Cosmetic] Flag emoji are used throughout the dashboard (Fixed 2026-10-01)

- **Where**: `/dashboard` Top threat IPs, `/dashboard/ips` Country column,
  `/dashboard/verdicts/[id]` header.
- **Steps to reproduce**: Load any of those pages with geo-enriched IP data.
- **Actual**: Country flags render as emoji, for example
  `🇩🇪 DE · Hetzner Online GmbH`. `frontend/DESIGN_SYSTEM.md` states plainly
  under "What This System Is Not": "No emoji in UI."
- **Expected**: Country code and ASN text only, or a non-emoji indicator.
- **Suspected file(s)**: `frontend/src/app/dashboard/page.tsx`,
  `frontend/src/components/dashboard/AllIpsTab.tsx`,
  `frontend/src/app/dashboard/verdicts/[id]/page.tsx`.

**Fix**: removed the `flagEmoji()` helper and its call sites from all three
files, now just plain country code and ASN org text. Verified via code
review and `npx tsc --noEmit` that no caller of the removed helper remains.

## [Severity: Cosmetic] Small copy and formatting issues on the Overview and verdict detail (Fixed 2026-10-01)

- **Where**: `/dashboard` Top threat IPs, `/dashboard/verdicts/[id]` raw log
  sample, "Cost prevented" stat card.
- **Actual**:
  - "1 hits" is not pluralised (shows for any IP with a single hit).
  - The raw log caption always reads "5 most suspicious requests from this
    batch" even when fewer lines are shown (3 in this run).
  - "Cost prevented" is always formatted as USD (`$2,530.50`) even for an org
    whose `home_country` is IN and whose billing UI is showing INR.
  - In the Top threat IPs list the IP and the country/ASN line sit flush against
    each other with no visible gap at the tested width.
- **Expected**: Correct pluralisation, a caption that reflects the actual count,
  a currency consistent with the rest of the product.
- **Suspected file(s)**: `frontend/src/app/dashboard/page.tsx`,
  `frontend/src/app/dashboard/verdicts/[id]/page.tsx`.

**Fix**: `{tip.count} hit{tip.count !== 1 ? "s" : ""}` for correct
pluralisation; the raw-log caption now reads `{v.sample_logs.length} most
suspicious request{s}` using the real rendered count instead of a hardcoded
5; "Cost prevented" now uses the same timezone/locale India heuristic the
Settings page already uses for its own currency toggle, rendering ₹ with
`en-IN` formatting for an India-locale session instead of always `$`; the
Top threat IPs row got `gap: "8px"` and `flexWrap: "wrap"` so the IP and
country/ASN text no longer sit flush together at narrow widths. Verified via
direct API check (seeded a verdict with exactly 1 hit, confirmed
`top_ips[0].count === 1` and the component now renders "1 hit" not "1
hits"; seeded `sample_logs` with 3 entries, confirmed the caption now reads
"3 most suspicious requests"). `npx tsc --noEmit` clean.

---

# Settings

## [Severity: High] Only 11 AWS regions are selectable, in both the wizard and the full Settings page (Fixed 2026-10-01)

- **Where**: `/dashboard/settings` S3 Log Ingestion "AWS region" select, and
  step 3 of the guided `LogSourceWizard`.
- **Steps to reproduce**: Open either control and read the options.
- **Expected**: Every region where a customer can realistically hold an S3
  bucket.
- **Actual**: The list is hardcoded to `us-east-1, us-east-2, us-west-1,
  us-west-2, eu-west-1, eu-west-2, eu-central-1, ap-south-1, ap-southeast-1,
  ap-southeast-2, ap-northeast-1`. There is no free-text fallback. A customer in
  `ca-central-1`, `eu-west-3`, `eu-north-1`, `ap-northeast-2`, `sa-east-1` or
  any other region cannot complete onboarding at all, and the product's whole
  pitch is zero-integration S3 access.
- **Suspected file(s)**: `frontend/src/app/dashboard/settings/page.tsx`,
  `frontend/src/components/dashboard/LogSourceWizard.tsx`.

**Fix**: added `frontend/src/lib/awsRegions.ts`, a single shared `AWS_REGIONS`
list covering every standard public AWS region (29 total, excludes only
GovCloud and China, which are isolated partitions needing separate accounts
not reachable via this product's cross-account IAM role). Both the Settings
page and `LogSourceWizard` now import this instead of each keeping their own
hardcoded 11-region copy. The backend had its own independent allow-list
(`api/routes/clients.py`'s `_ALLOWED_REGIONS`) that would have silently 422'd
a save of any of the new regions even after the frontend offered them, so
that set was updated to match. Verified live: registered a fresh account,
confirmed the region `<select>` now lists all 29 regions including the
previously-missing `ca-central-1`, `eu-west-3`, `eu-north-1`,
`ap-northeast-2`, and `sa-east-1`, then confirmed `PATCH /clients/me` with
`aws_region: "ca-central-1"` returns 200 and persists (previously would have
422'd). Test account cleaned up afterward. `npx tsc --noEmit` clean, backend
imports clean, `python workers/tests/test_process_logs.py` still 3/3 passing.

## [Severity: Medium] Every paid tier is told it is on the free plan (Fixed 2026-10-01)

- **Where**: `/dashboard/settings`, Plan & Billing, under "Current plan".
- **Steps to reproduce**:
  1. Set an org's `tier` to `starter`, then `growth`, then `pro`.
  2. Reload Settings each time and read the two lines under "Current plan".
- **Expected**: The plan name and the description agree.
- **Actual**: The name is correct in every case (Starter / Basic / Growth / Pro,
  matching the internal codes `free` / `starter` / `growth` / `pro`), but the
  sentence below it is hardcoded: "You're on the free Starter plan. Upgrade to
  unlock longer threat history retention, email alerts, and automatic
  blocking." A paying Pro customer reads that they are on the free plan. This is
  the same recurring tier-display bug class `CONTEXT.md` warns about, just moved
  from the name to the description.
- **Suspected file(s)**: `frontend/src/app/dashboard/settings/page.tsx`
  (billing section).

**Fix**: the description line was keyed off `billing_provider !== "stripe"`
(true for every non-Stripe org, free or paid, e.g. a pilot/promo-code org
or a Razorpay org before its first charge), not the actual tier. It now
checks `config?.tier === "free"` for the hardcoded free-plan copy, and falls
back to `` `You're on the ${tierDisplayName(config?.tier)} plan.` `` for any
other tier with no active Stripe/Razorpay subscription, reusing the same
`tierDisplayName()` helper the plan name itself already uses so the two
lines can't disagree again. Verified live: set a test org's tier to `growth`
with no billing provider, confirmed Settings now reads "You're on the Growth
plan." instead of the free-plan message; reset to `free` and confirmed the
original copy is unchanged (no regression). Test data cleaned up afterward.
`npx tsc --noEmit` clean.

## [Severity: Medium] Saving in Settings gives no success confirmation (Not reproduced 2026-10-01)

- **Where**: `/dashboard/settings`, the "Save" button covering S3, home country
  and alert settings.
- **Steps to reproduce**: Change any field and click "Save". Watch the button.
- **Expected**: A "Saved" state or an inline confirmation, as the Change
  Password section correctly does ("Password changed. Other sessions have been
  signed out.").
- **Actual**: The button goes "Save" to "Saving…" and straight back to "Save".
  Nothing confirms the write succeeded. Values are persisted correctly
  (verified in Postgres), so this is purely missing feedback, but on a page
  where the only other signal is an unrelated connection badge it reads as a
  failure.
- **Suspected file(s)**: `frontend/src/app/dashboard/settings/page.tsx`.

**Checked 2026-10-01**: `handleSave()` already sets a `saved` state to `true`
on a successful `PATCH /clients/me` and renders a green "Saved" span next to
the button for 3 seconds (`frontend/src/app/dashboard/settings/page.tsx`,
`handleSave`). Live-verified: changed the S3 bucket field and clicked "Save",
the inline "Saved" confirmation appeared immediately next to the button.
Could not reproduce the finding against the current code, no change made.
Possibly already fixed between the QA pass and this session, or the original
repro hit a code path this session didn't (e.g. a field outside this form).
Test data cleaned up afterward.


## [Severity: Medium] In-app `#anchor` links to Settings do not scroll (Fixed 2026-10-01)

- **Where**: Every in-app link to a Settings anchor: the MFA nudge banner
  ("Set up MFA" to `#mfa`), the StatusHeader "S3 error" badge and the dashboard
  "Check Settings" link (both to `#s3`), the onboarding "I'd rather use the full
  Settings page" escape hatch, and the onboarding Configure buttons
  (`#s3`, `#billing`, `#alerts`, `#waf`).
- **Steps to reproduce**:
  1. From `/dashboard`, click "Set up MFA" in the yellow nudge banner.
  2. Observe the scroll position on the Settings page.
- **Expected**: The page scrolls to the Two-Factor Authentication section.
- **Actual**: The URL becomes `/dashboard/settings#mfa` but `window.scrollY` is
  0 while the `#mfa` element is 3,916px down the page. The user lands on Plan &
  Billing with no hint that they should scroll. A hard page load of the same URL
  **does** scroll correctly (measured 3,877px), so this only affects client-side
  navigation, which is how every in-app link behaves.
- **Suspected file(s)**: `frontend/src/app/dashboard/settings/page.tsx` (needs
  an effect that scrolls to `location.hash` once the async config has rendered),
  `frontend/src/components/dashboard/OnboardingModal.tsx` (`goTo`).

**Fix**: added a `useEffect` in `settings/page.tsx` keyed on `loading` that,
once the page's own "Loading…" placeholder gives way to the real content
(the anchor targets like `#mfa` don't exist in the DOM before then),
scrolls `window.location.hash`'s target into view. Didn't need to touch
`OnboardingModal.tsx`'s `goTo()`, it already navigates to the right
`/dashboard/settings#anchor` URL, the settings page just never reacted to an
in-place hash on client-side navigation, same root cause for every caller
listed above. Verified live: clicked "Set up MFA" in the dashboard nudge
banner (the exact repro), landed on `/dashboard/settings#mfa` with
`window.scrollY` now ~4182px (matching the `#mfa` section's actual offset),
not 0. Test account cleaned up afterward. `npx tsc --noEmit` clean.

## [Severity: Medium] A viewer can open the Settings page directly and sees the whole thing (Fixed 2026-10-01)

- **Where**: `/dashboard/settings` as a `viewer` role.
- **Steps to reproduce**:
  1. Sign in as a viewer. Confirm the sidebar has no Settings link.
  2. Type `/dashboard/settings` in the address bar.
- **Expected**: A redirect, or a "you do not have access to this page" state,
  matching the fact that the nav link is deliberately hidden.
- **Actual**: The full Settings page renders: plan cards with working "Select"
  buttons, the billing-period toggle, the GSTIN field, the S3 form, the AWS
  Access section, MFA setup, Change Password, Team Members and the Danger Zone.
  The backend does its job (`/clients/me`, `/billing/status`, `/org/members`,
  `/org/invites` all return 403 and "Current plan" renders as the null
  placeholder), so no data leaks, but the user is presented with a page full of
  controls that cannot work.
- **Suspected file(s)**: `frontend/src/app/dashboard/settings/page.tsx` (no
  role guard), `frontend/src/proxy.ts`.

**Fix**: `loadConfig()`'s initial `GET /clients/me` now checks for a 403
specifically (role-only route, 403 means viewer) and sets an `accessDenied`
flag instead of falling through to the generic error path. The page's main
render now returns early with a plain "You don't have access to this page.
Settings is only available to organisation owners and admins..." message
instead of the full form when that flag is set. Verified live: invited a
second account as a `viewer`, signed in as it, navigated straight to
`/dashboard/settings`, and got the access-denied message instead of a page
full of controls that 403 on every action. Test accounts and org cleaned up
afterward. `npx tsc --noEmit` clean.

## [Severity: Low] A stale Razorpay error persists after switching currency to USD (Fixed 2026-10-01)

- **Where**: `/dashboard/settings`, Plan & Billing.
- **Steps to reproduce**:
  1. With INR selected, click any plan's "Select" and accept the blocking
     agreement, producing "Razorpay is not configured on this server."
  2. Click "Switch to USD".
- **Expected**: The error clears, since the non-INR panel does not involve
  Razorpay at all.
- **Actual**: The India-only panel renders correctly (newsletter form, LinkedIn,
  support mailto, no dead checkout button, which is the intended behaviour) but
  the stale "Razorpay is not configured on this server." banner stays above it.
- **Suspected file(s)**: `frontend/src/app/dashboard/settings/page.tsx` (clear
  `billingError` on the currency toggle).

**Fix**: the currency toggle button now also calls `setBillingError(null)`.
Verified live: selected a plan on a fresh free-tier org, accepted the
blocking agreement, reproduced the real "Razorpay is not configured on this
server." error, clicked "Switch to USD", and confirmed the error banner was
gone immediately while the USD/India-unavailable panel rendered normally.
Test account cleaned up afterward. `npx tsc --noEmit` clean.

---

# Alerts and tier gating

## [Severity: Medium] The free tier can configure alerts and "Send test alert" succeeds, but real alerts never fire (Fixed 2026-10-01)

- **Where**: `/dashboard/settings` Alerts section and `/dashboard/alerts`
  Notifications tab, on an org with `tier = "free"`.
- **Steps to reproduce**:
  1. On a free-tier org, set an alert email in Settings and save.
  2. Go to `/dashboard/alerts`, Notifications tab.
  3. Click "Send test alert".
- **Expected**: The alerts controls are gated or clearly labelled as paid-only,
  consistent with the guided onboarding panel, which already says "Email alerts
  on critical threats require a paid plan."
- **Actual**: The Settings Alerts section renders with no tier gating at all.
  The Notifications tab says "Sending alerts to: qa-alerts@clewqa.test" and the
  test button reports "Test alert sent to qa-alerts@clewqa.test." The email is
  genuinely sent. But `workers/tasks/send_alerts.py` skips any org whose tier is
  not in `MANUAL_BLOCK_TIERS` and returns
  `{"status": "skipped", "reason": "free_tier"}`, so no real alert will ever
  arrive. The product actively tells a free customer their alerting works.
- **Suspected file(s)**: `api/routes/alerts.py` (`send_test_alert` has no tier
  check), `frontend/src/app/dashboard/settings/page.tsx` (Alerts section),
  `frontend/src/components/dashboard/NotificationsTab.tsx`.

**Fix**: `send_test_alert` now checks `org.tier` against the same
`MANUAL_BLOCK_TIERS` set `send_alerts.py`'s real path already gates on, and
returns `{"status": "failed", "message": "Email alerts require an active
paid plan."}` instead of sending a real test email that implies working
alerting. Both the Settings Alerts section and the Notifications tab now
show an inline note on free tier ("Email alerts require an active paid
plan...") instead of rendering as if alerts were fully functional; fields
stay editable so an admin can pre-configure before upgrading. Verified live
on a free-tier org: the Settings note appeared, and clicking "Send test
alert" on the Notifications tab now reports "Email alerts require an active
paid plan." instead of claiming success. Test data cleaned up afterward.
`npx tsc --noEmit` clean, backend imports clean, `python
workers/tests/test_process_logs.py` still 3/3 passing.

## [Severity: Medium] Basic tier sees automatic-blocking framing on the WAF and Cloudflare sections (Fixed 2026-10-01)

- **Where**: `/dashboard/settings`, WAF Configuration and Cloudflare
  Configuration, on `tier = "starter"` (marketing name Basic).
- **Steps to reproduce**:
  1. Set an org to `starter`. Reload Settings.
  2. Read the description under each blocking section.
  3. Repeat on `growth` and compare.
- **Expected**: Basic is manual-only. It should say so, and ideally offer an
  upgrade path to automatic blocking.
- **Actual**: Both tiers see byte-identical copy: "Push a block rule to your AWS
  WAF IP set **when a high-confidence threat is detected**" and the same for
  Cloudflare. That is automatic-blocking framing. Nothing on the page tells a
  Basic customer that only the manual one-click button will ever act, and
  nothing tells them upgrading to Growth is what enables unattended blocking.
- **Suspected file(s)**: `frontend/src/app/dashboard/settings/page.tsx` (the WAF
  and Cloudflare section headers and descriptions).

**Fix**: added a frontend `AUTO_BLOCK_TIERS` constant mirroring
`api/tiers.py`'s own list (`growth`, `pro`, `enterprise`). The WAF and
Cloudflare section descriptions now branch on it: `AUTO_BLOCK_TIERS` orgs
keep the existing "when a high-confidence threat is detected" copy, anything
else (Basic/starter) gets "Push a block rule ... with one click from a
verdict. Automatic, unattended blocking is available on Growth and above."
Verified live: set a test org to `starter`, confirmed the Settings page now
shows the manual-only copy with the upgrade hint; set the same org to
`growth` and confirmed the original automatic-blocking copy is unchanged (no
regression). Test data cleaned up afterward. `npx tsc --noEmit` clean.

---

# Cross-tier

Everything else in the cross-tier sweep behaved correctly and is recorded here
so it does not get re-tested: `free` showed no blocking configuration sections
at all and the upgrade prompt "Available on any paid plan"; `starter` and above
showed the WAF and Cloudflare forms; `growth` and `pro` showed the real threat
explanation on the verdict detail page while `free` and `starter` showed
"Upgrade to Growth to unlock threat explanations"; the usage banner fired
correctly at 95 percent of the Pro cap ("You're at 95% of your monthly call
volume (190,000,000 / 200,000,000)"); the marketing plan **name** was correct at
every tier. The two cross-tier defects found are filed above (the hardcoded free
plan description, and the Basic automatic-blocking copy).

---

# Public site

## [Severity: Low] `/pricing` has no heading elements at all (Fixed 2026-10-01)

- **Where**: `http://localhost:3000/pricing`.
- **Steps to reproduce**: Load the page and query for `h1, h2, h3`.
- **Expected**: At least an `<h1>`.
- **Actual**: Zero headings on the page. The entire pricing table, including
  tier names, is `<p>` elements. The `<title>` is the bare word "Pricing".
  Screen-reader users get no document structure and the page has no `h1` for
  search engines. The same `Pricing` component is fine on the home page only
  because other sections supply the headings.
- **Suspected file(s)**: `frontend/src/components/home/Pricing.tsx`,
  `frontend/src/app/pricing/page.tsx`.

**Fix**: `Pricing` now accepts an optional `standalone` prop; when set, the
existing "Pricing" kicker label renders as an `<h1>` (identical visual
style, just a different tag) instead of a `<p>`. `pricing/page.tsx` passes
`standalone`; the home page's usage is unchanged (still a `<p>`, since the
Hero above it already supplies the page's one `<h1>`). Verified live:
`/pricing` now has exactly one heading, `<h1>Pricing</h1>`, and the home page
still has exactly one `<h1>` (the Hero's), no duplicate. `npx tsc --noEmit`
clean.

## [Severity: Low] The navbar "Pricing" link always goes to the home page anchor, even from `/pricing` (Fixed 2026-10-01)

- **Where**: Navbar on every page.
- **Steps to reproduce**:
  1. Open `/pricing`.
  2. Click "Pricing" in the navbar.
- **Expected**: Stay on `/pricing`, or at least not navigate away from the
  dedicated page the user is already on.
- **Actual**: The link is `/#pricing`, so it navigates to the home page and
  scrolls. The footer's "Pricing" link points at `/pricing`, so the two
  disagree, and the standalone route is effectively orphaned from the main nav.
- **Suspected file(s)**: `frontend/src/components/layout/Navbar.tsx`.

**Fix**: changed the navbar link's `href` from `/#pricing` to `/pricing`,
matching the footer. The existing `onClick` smooth-scroll override (for when
the visitor is already on `/`) is untouched, so home-page behavior is
identical; clicking "Pricing" from `/pricing` itself now just stays there
instead of navigating to `/`. Verified live: confirmed the navbar's Pricing
link now resolves to `/pricing`, same as the footer. `npx tsc --noEmit`
clean.

## [Severity: Low] Two legal pages were amended on 2026-10-01 but still say "Last updated: August 10, 2026" (Fixed 2026-10-01)

- **Where**: `/legal/privacy` and `/legal/subscription-agreement`.
- **Steps to reproduce**: Open each page and read the date under the title, then
  compare against the content.
- **Expected**: The date reflects the last substantive change, as it correctly
  does on `/legal/terms` and `/legal/refund-policy` (both October 1, 2026).
- **Actual**: Both still show August 10, 2026 even though Privacy gained a
  "Data controller" section with the registered entity details and had the Groq
  subprocessor entry re-added, and the Subscription Agreement gained its first
  ever `h2` ("Legal entity"). A stale "last updated" on a legal page is a
  compliance smell, not just a typo.
- **Suspected file(s)**: `frontend/src/app/legal/privacy/page.tsx`,
  `frontend/src/app/legal/subscription-agreement/page.tsx`.

**Fix**: updated both `lastUpdated` props to "October 1, 2026", matching
terms/refund-policy. Verified live: `/legal/privacy` now reads "Last
updated: October 1, 2026".

## [Severity: Cosmetic] `hover:opacity-80` violates the design system's stated button rule (Fixed 2026-10-01)

- **Where**: Hero "Get started", the Pricing CTA buttons, the Clew Audit
  "Request audit" button, the CostCalculator CTA, the footer social icons, and
  the 404 page's button.
- **Steps to reproduce**: Hover any of those controls.
- **Expected**: Per `frontend/DESIGN_SYSTEM.md` under Buttons: "No opacity
  changes on hover. Always invert or increase border contrast." And under What
  This System Is Not: "No animations beyond a simple 150ms color transition on
  interactive elements."
- **Actual**: Seven call sites use `transition-opacity hover:opacity-80` (or
  `hover:opacity-70`): `frontend/src/components/home/Hero.tsx:31`,
  `frontend/src/components/home/Pricing.tsx:236` and `:295`,
  `frontend/src/components/home/CostCalculator.tsx:323`,
  `frontend/src/components/layout/Footer.tsx:85` and `:97`,
  `frontend/src/app/not-found.tsx:34`. No rounded corners, shadows or gradients
  were found anywhere, so this is the only systematic visual violation.
- **Suspected file(s)**: the seven files listed above.

**Fix**: replaced every `transition-opacity hover:opacity-80`/`-70` with
`transition-colors` plus an `onMouseEnter`/`onMouseLeave` pair, inverting
background/foreground for solid buttons (Hero's "Get started", the
highlighted Pricing CTA, CostCalculator's CTA), increasing border contrast
for outline buttons (the non-highlighted Pricing CTAs, "Request audit", the
404 page's "Back to home"), and swapping to the muted text color for the two
borderless footer icon links. `Footer.tsx` had no `"use client"` directive,
so adding event handlers there initially broke the page with "Event handlers
cannot be passed to Client Component props" (caught by `tsc`/browser
console, not type-checking, since inline event handler props are valid
JSX/TS syntax on a Server Component and only fail at render time); added
`"use client"` to fix it, consistent with it rendering `NewsletterForm`
(itself interactive) already. Verified live: hovering the Hero button now
flips background from light to dark (`rgb(245,245,245)` to
`rgb(13,13,13)`), hovering the LinkedIn icon changes its color from
`rgb(245,245,245)` to `rgb(136,136,136)` (muted), and both `/` and
`/pricing` render with no console errors or error boundary. `npx tsc
--noEmit` clean, `grep -rn "hover:opacity" src/` finds nothing, `python
workers/tests/test_process_logs.py` still 3/3 passing.

## [Severity: Cosmetic] Em dashes in user-visible copy, page metadata and outbound email (Fixed 2026-10-01)

- **Where**: Several places a customer actually sees. The repo's own hard rule
  (`frontend/DESIGN_SYSTEM.md`, `TODO.md`, `.github/copilot-instructions.md`) is
  "Never use an em dash."
- **Steps to reproduce**: Load the pages, or trigger the emails.
This report cannot quote the offending strings literally, so `[EMDASH]` below
stands in for the character at each site.

- **Actual**, visible copy:
  - `frontend/src/components/dashboard/MfaNudgeBanner.tsx:57`,
    "Secure your account [EMDASH] enable two-factor authentication." Shown on
    every dashboard page until dismissed.
  - `frontend/src/app/legal/refund-policy/page.tsx:20`, a rendered `h2`:
    "2. First payment [EMDASH] 72-hour remorse window".
  - `frontend/src/app/dashboard/settings/page.tsx:1699`, `:1702`, `:1737`, the
    MFA backup-codes panel: "MFA enabled [EMDASH] save your backup codes",
    "Save them somewhere safe [EMDASH] they will not be shown again",
    "I've saved them [EMDASH] Done".
  - `frontend/src/components/dashboard/DashboardGate.tsx:68`,
    "This creates your organisation [EMDASH] you'll be its owner".
- **Actual**, metadata and email:
  - `frontend/src/app/layout.tsx:27` and `:36`, the OG title and image alt:
    "Clew [EMDASH] API Abuse Detection for SaaS". This is what appears in link
    previews.
  - `frontend/src/app/legal/terms/page.tsx:7` and
    `frontend/src/app/legal/privacy/page.tsx:7`, meta descriptions.
  - `workers/tasks/send_alerts.py:49`, the alert email subject line:
    `[Clew] CRITICAL threat detected [EMDASH] 203.0.113.42`. Confirmed in a
    real sent message during the run.
  - `api/auth_utils.py`, the org invite email body: "ignore this email
    [EMDASH] no account will be created."
- **Expected**: A period, comma, colon or parentheses.
- **Note**: The `[EMDASH] Select format [EMDASH]` select placeholders and the
  bare-character null-value placeholders in tables are the established,
  legitimate exception and are not included above.

**Fix**: replaced every em dash listed above with a period, comma, colon or
parentheses, matching whichever reads most naturally at each site (the
MfaNudgeBanner site was already fixed to a colon before this session, left
as-is). Did not touch the em dashes in code comments or log messages in the
same files (`workers/tasks/send_alerts.py`'s module docstring and a debug
log line, `DashboardGate.tsx`'s comment), those aren't user-visible copy and
are out of this finding's stated scope. Verified via `grep -rn` on every
targeted file that only comment/log-message em dashes remain, and live:
registered an account, invited a teammate, and confirmed the real sent
invite email body no longer contains an em dash. `npx tsc --noEmit` clean,
backend and worker modules still import, `python
workers/tests/test_process_logs.py` still 3/3 passing.

## [Severity: Cosmetic] "as a Admin" / "as a Viewer" in the invite email and accept page (Fixed 2026-10-01)

- **Where**: Org invite email body and `/accept-invite` heading text.
- **Actual**: "You have been invited to join Clew QA Org's security dashboard as
  a Admin."
- **Expected**: "as an Admin".
- **Suspected file(s)**: `api/auth_utils.py` (`send_org_invite_email`),
  `frontend/src/app/accept-invite/page.tsx`.

**Fix**: both `send_org_invite_email` and the accept-invite page now pick
"a" or "an" based on whether the capitalised role label starts with a
vowel (`Admin` to "an Admin", `Viewer` stays "a Viewer"), instead of a
hardcoded "a". Verified live: invited a teammate and confirmed the real
sent email reads "as a Viewer"; confirmed the article logic directly
produces "as an Admin" for the admin role. `npx tsc --noEmit` clean,
backend imports clean.

---

# Responsive

## [Severity: High] The dashboard is unusable at a mobile viewport (Fixed 2026-10-01)

- **Where**: `/dashboard`, `/dashboard/alerts`, `/dashboard/ips` at a 390px
  viewport (375 CSS pixels).
- **Steps to reproduce**:
  1. Sign in, then resize to 390 x 844 (or use a phone).
  2. Visit each dashboard page and try to scroll or tap anything on the right.
- **Expected**: Either a responsive layout, or at minimum no page-level
  horizontal overflow.
- **Actual**: Measured `document.scrollWidth` against a 375px client width:
  `/dashboard` 1078px (703px of overflow), `/dashboard/alerts` 995px (620px),
  `/dashboard/ips` 1211px (836px). The sidebar stays a fixed 192px and never
  collapses, so roughly half the remaining width is taken by nav. The stat-card
  row, the severity filter checkboxes, the date-range buttons, the IP filter
  input and every data table all extend past the viewport.
- **Expected vs public site**: the public pages are fine. `/`, `/pricing` and
  `/legal/terms` all measured zero page-level overflow at the same width, and
  `/docs` only overflows inside its own scrollable table container, which is
  correct.
- **Suspected file(s)**: `frontend/src/app/dashboard/layout.tsx`,
  `frontend/src/components/dashboard/Sidebar.tsx`,
  `frontend/src/app/dashboard/page.tsx`,
  `frontend/src/components/dashboard/VerdictsTab.tsx`,
  `frontend/src/components/dashboard/AllIpsTab.tsx`.

**Fix**: added a shared `useIsMobile()` hook (`frontend/src/lib/useIsMobile.ts`,
768px breakpoint via `matchMedia`). Below that width, `Sidebar.tsx` no longer
renders the fixed 192px column at all: it renders a slim fixed top bar
(logo + hamburger) instead, and the org switcher/nav/sign-out move into a
full-screen drawer toggled by the hamburger, closing on any nav or org click.
`DashboardContentShell` reserves top padding for that bar on mobile instead
of right-margin for the onboarding panel (which already caps itself to
`92vw` and doesn't need the reservation on a screen too narrow to dock it
meaningfully anyway). Added `flexWrap: "wrap"` to the Overview stat-card row
and the Verdicts tab's date-range preset row, the two flex rows that still
had none; the data tables already scroll within themselves from the High #4
fix just above. Verified live at a 390x844 viewport: registered a fresh
account, seeded a verdict/IP so the tables had real content, and measured
`document.scrollWidth` against `document.clientWidth` on all three pages,
0px of overflow on each (previously 620 to 836px). Confirmed the hamburger
menu opens, the drawer lists all nav links, and tapping "Settings" actually
navigates there and closes the drawer. Test account and data cleaned up
afterward. `npx tsc --noEmit` clean, `python workers/tests/test_process_logs.py`
still 3/3 passing.

---

# Errors and edge states

## [Severity: Low] Dead sessions loop `/clients/me` to `/auth/refresh` forever in open tabs (Fixed 2026-10-01)

- **Where**: Any open dashboard tab after the session becomes invalid (account
  deleted, refresh token revoked).
- **Steps to reproduce**:
  1. Leave a dashboard tab open.
  2. Invalidate that account's session (delete the account from another tab, or
     soft-delete the client row).
  3. Watch the API log.
- **Expected**: One failed refresh, the session-expired modal, then polling
  stops.
- **Actual**: An unbounded loop of `GET /clients/me 401` followed by
  `POST /auth/refresh 401`, repeating roughly every few seconds for as long as
  the tab is open. Several abandoned tabs produced hundreds of these pairs
  during this run. The onboarding poll and `apiFetch`'s refresh retry keep
  firing after the session is unrecoverable.
- **Suspected file(s)**: `frontend/src/lib/api.ts` (no "give up after refresh
  fails" latch), `frontend/src/components/dashboard/OnboardingModal.tsx` (poll
  does not stop on auth failure).

**Fix**: added a module-level `sessionExpired` latch in `api.ts`. Once a
silent refresh fails once (`notifySessionExpired()` fires, the existing
session-expired modal event), `apiFetch` short-circuits every subsequent
call for any caller, onboarding poll, dashboard summary, anything, returning
a synthetic 401 with zero network requests, instead of every independent
poller repeating its own doomed GET/refresh cycle forever. The latch is a
plain module variable, not per-request state, so it's shared by every caller
in the tab. `SessionExpiredModal`'s "Log in" button calls the new
`resetSessionExpired()` export before redirecting, since Next's client-side
routing keeps this module alive across the navigation to `/login`, a literal
page reload isn't guaranteed. Verified live: registered a test account,
soft-deleted the `Client` row (deleted_at) to invalidate the session while
the dashboard tab stayed open, confirmed the session-expired modal appeared
after the first failed cycle, then watched 0 further `/clients/me` or
`/auth/refresh` requests over the next 16 seconds (previously would have
been several repeated pairs). Test data cleaned up afterward. `npx tsc
--noEmit` clean, `python workers/tests/test_process_logs.py` still 3/3
passing.

## Verified working, recorded so it is not re-tested

These were exercised and behaved correctly, so they are not findings:

- 404 handling: `/this-route-does-not-exist` returns a real 404 with a styled
  "This page doesn't exist." page; `/dashboard/nope` while logged out redirects
  to `/login?next=%2Fdashboard%2Fnope`; the API returns
  `404 {"detail":"Not Found"}` for unknown routes.
- Registration validation: empty required fields, malformed email,
  `minlength` on password, the live password-strength meter ("Too weak" to
  "Strong"), ToS enforcement ("You must agree to the Terms of Service and
  Privacy Policy."), and an invalid promo code ("This promo code is no longer
  available.").
- Turnstile test keys work end to end on register and forgot-password.
- Email verification: wrong code gives "Invalid or expired code.", correct code
  signs in.
- MFA: setup with QR plus manual key, TOTP activation, 10 backup codes, MFA
  challenge at login, "Use a backup code" path, successful backup-code login.
- Change password: wrong current password rejected, success message
  "Password changed. Other sessions have been signed out.", other sessions
  genuinely disappear from the session list.
- Account deletion: the owner-only warning copy is correct and mentions
  "Make owner"; typing `delete` leaves the button disabled while `DELETE`
  enables it; deletion redirects to `/login`; the deleted account cannot log
  back in (401) and the org is soft-deleted with the email anonymised to
  `deleted-<uuid>@deleted.clew`.
- Team invites (creation side): the domain ceiling correctly rejects an external
  email with a non-viewer role ("External collaborators can only be invited as
  Viewer."), same-domain admin and viewer invites send, pending invites list
  with Resend and Cancel works.
- Pricing math: annual is exactly 50 percent off in both currencies
  (INR 1,999 / 4,999 / 9,999 monthly against 11,994 / 29,994 / 59,994 annual;
  USD 49 / 129 / 249 against 294 / 774 / 1,494). Currency and period toggles
  both work. Free tier CTA is `/register`, paid tiers carry
  `/register?plan=<tier>`, Enterprise and Clew Audit both use the
  `support@clewsec.com` mailto.
- Docs page: all 24 TOC anchors resolve to real heading ids, scroll-spy updates
  on real scroll, tables scroll inside their own container at mobile width.
- All five `/legal/*` pages load with an `h1`, their TOC anchors resolve, and
  every internal cross-link points at a real route.
- Newsletter double opt-in: honeypot is correctly off-screen with
  `tabindex="-1"` and `aria-hidden="true"`, subscribe returns the generic
  message, the confirmation link works.
- Settings connection tests surface real, specific errors: the S3 save produced
  "Bucket '...' not found in region 'ap-south-1', check the bucket name and AWS
  region", the role ARN test produced the sts:ExternalId guidance, the WAF test
  produced the same, and the Cloudflare test produced "Invalid API token".
- GSTIN validation: an invalid value returns a clear 400 before the Razorpay
  503, and a valid one proceeds to the expected
  "Razorpay is not configured on this server."
- The Blocking Subscription Agreement modal triggers before the first checkout
  and acceptance persists.
- The non-INR billing panel renders instead of a dead checkout.
- Verdicts filters: severity multi-select, threat-type dropdown, date-range
  presets, page-size selector, and the IP prefix filter all return the expected
  counts.
- Blocked IPs tab: dual WAF and Cloudflare badges, the error tooltip on a failed
  Cloudflare block, and the unblock confirmation all render correctly.
- Celery worker and beat both start clean with all 11 tasks registered,
  including `push_block` and `push_unblock`.

---

## Counts by severity

Critical 2, High 6, Medium 11, Low 8, Cosmetic 5. Total 32.

The two Critical items (team invite accept always 500s, and the manual block
form crashing the IPs page) and the two session-security High items (invite
token minting a session without MFA, password reset bypassing MFA) are the ones
worth triaging first.
