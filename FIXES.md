# FIXES.md

Targeted QA pass, 2026-10-02. Scope was **only the changes** from the previous
`FIXES.md` fix pass (commit `023118c`) and `TODO.md` Phase 1 (uncommitted
working tree), not a full product scan. Driven through the real UI with browser
automation against the local dev stack.

## Test data created

A throwaway org (`Clew QA2 Org`), an owner (`qa2-owner@clewqa.test`), a viewer
(`qa2-viewer@clewqa.test`), 8 verdicts and 4 ip_memory rows were created, used,
and **deleted again**. Only the two pre-existing accounts (`jeff@clewsec.com`,
`onboardtest+...@example.com`) remain. `/tmp/clew_qa2_seed.py` was removed.

---

## [Severity: High] The hover rework contradicts an explicit decision, and the design doc now contradicts the code (Fixed 2026-10-02)

- **Where**: `Hero.tsx:31`, `CostCalculator.tsx:323`, `Pricing.tsx:236` and
  `:295`, `Footer.tsx:85` and `:97`, `not-found.tsx:34`, plus
  `frontend/DESIGN_SYSTEM.md`.
- **Steps to reproduce**:
  1. `grep -rn "hover:opacity" frontend/src/` returns nothing.
  2. Open `Hero.tsx` and read the "Get started" button's `onMouseEnter`.
  3. Read the two paragraphs `DESIGN_SYSTEM.md` gained in the Phase 1 rewrite.
- **Expected**: `TODO.md` Phase 1 item 4 ("Leave alone, explicitly confirmed")
  says these 7 buttons keep their `hover:opacity-70`/`hover:opacity-80`
  treatment, that inverting them into a color swap "was an earlier idea in the
  same conversation and was explicitly declined."
- **Actual**: The earlier `FIXES.md` cosmetic fix converted all 7 to a
  background-and-text color invert on hover, which is the exact change that was
  declined. The two passes overlapped and the later decision lost. It also
  leaves the design doc wrong twice over: it now says "The marketing site's own
  `hover:opacity-70`/`hover:opacity-80` text buttons are a separate, deliberate
  exception" when zero such buttons remain, and it says "What is actually
  off-limits is hue/color changes on the marketing site specifically" while the
  Hero button now performs exactly that on the marketing site.
- **Suspected file(s)**: the 7 files above, and `frontend/DESIGN_SYSTEM.md`.
  Decide which behaviour is wanted, then make the code and the doc agree. This
  is a decision, not a bug to silently patch.
- **Fix**: re-read `TODO.md` Phase 1 item 4 and `DESIGN_SYSTEM.md` directly
  rather than re-litigating the decision. TODO.md's text is explicit and
  already settled: the 7 buttons keep `hover:opacity-70`/`hover:opacity-80`,
  inverting them to a color swap was explicitly declined. `DESIGN_SYSTEM.md`
  already carried the correct, final wording from that same decision (opacity
  hover fine everywhere, hue/color changes off-limits on marketing only), so
  only the code was wrong. Reverted all 7 call sites to their original
  `hover:opacity-70`/`hover:opacity-80` classes, removed the `onMouseEnter`/
  `onMouseLeave` color-invert handlers, and removed `Footer.tsx`'s now-unneeded
  `"use client"` directive (no remaining client-only hooks/handlers in that
  file). No `DESIGN_SYSTEM.md` edit needed. Verified live in the browser,
  dark and light mode: all 7 buttons (`Hero.tsx`, `CostCalculator.tsx`,
  `Pricing.tsx` x2, `Footer.tsx` x2, `not-found.tsx`) render with their
  original opacity-only classes and no color-invert handlers.

## [Severity: Medium] The disabled connection method reads as the selected one

- **Where**: `/` (home), "Ways to connect" section,
  `frontend/src/components/home/WaysToConnect.tsx`.
- **Steps to reproduce**:
  1. Load the home page and scroll to "Ways to connect".
  2. Compare the "S3 log pull" cell against the "Direct log push" cell, in both
     light and dark mode.
- **Expected**: The live method is the visually prominent one; the unavailable
  one recedes.
- **Actual**: Backwards in both themes. The cells sit on a grid whose container
  background is `var(--color-border)`, and each cell paints `var(--color-bg)`
  over it. At `opacity: 0.4` the disabled cell lets the border grey show
  through, so it renders as a filled block while the live cell blends into the
  page. Measured in dark mode: live cell resolves to `#0D0D0D`, disabled to
  roughly `#1E1E1E` against a `#0D0D0D` page. In light mode the disabled cell
  renders as a solid grey tab, which reads unmistakably as "selected".
  Screenshot captured. The tooltip-free, label-free fade is otherwise exactly
  as specified, only the direction of emphasis is inverted.
- **Suspected file(s)**: `frontend/src/components/home/WaysToConnect.tsx`. Fade
  the cell's text/content rather than the cell itself, or give the live cell an
  explicit selected treatment instead of relying on the disabled one receding.
- **Fix**: moved the `opacity: method.live ? 1 : 0.4` from the cell `div`
  (which painted `var(--color-bg)`, letting the grid's grey background show
  through at reduced opacity) onto the label `p` only. Both cells now paint a
  fully opaque `var(--color-bg)`, matching the page background exactly, and
  only the disabled label's text fades. Verified live in both themes: dark
  mode both cells now resolve to the same `rgb(13, 13, 13)` background with
  only the disabled label at 0.4 text opacity; light mode both resolve to
  `rgb(245, 245, 245)`, same result. The live method no longer blends into
  the page and the disabled one no longer reads as selected.

## [Severity: Medium] The dashboard Overview still overflows at mobile width

- **Where**: `/dashboard` at a 375px viewport.
- **Steps to reproduce**:
  1. Sign in, resize to 375px wide.
  2. Visit `/dashboard` and compare `document.documentElement.scrollWidth`
     against `clientWidth`.
- **Expected**: No page-level horizontal overflow, matching the other two
  dashboard pages after the responsive fix.
- **Actual**: `scrollWidth` 442 against `clientWidth` 360, so 82px still spills.
  `/dashboard/alerts` (360 vs 360) and `/dashboard/ips` (375 vs 375) are both
  clean, so the responsive fix landed for those two but not here. The culprit
  is the trend-chart-plus-Top-threat-IPs flex row, which never stacks: the "Top
  threat IPs" panel measures a right edge of 442px. The date-range buttons
  (`7d`/`30d`) also end at 366px. This is a big improvement on the 703px
  overflow originally reported, but the finding is not fully closed.
- **Suspected file(s)**: `frontend/src/app/dashboard/page.tsx`, the
  `display: flex` wrapper around the chart and Top IPs panels.
- **Fix**: added `flexWrap: "wrap"` to the chart+Top-IPs row and gave each
  child a real `flexBasis`/`minWidth` (`"2 1 320px"`/`280px` for the chart,
  `"1 1 220px"`/`220px` for Top IPs) instead of `flex: "N 1 0"` with no
  minimum, so the row genuinely stacks instead of being squeezed. Also made
  the title+period-selector row wrap (`flexWrap`, explicit `gap`). Fixing
  those two surfaced a second, smaller pre-existing overflow at the exact
  same viewport: the stat-card row's `StatCard` used `flex: "1 1 0"` with
  `minWidth: 0`, which let all 4 cards shrink to ~65px wide in a single row
  rather than wrapping, so "Cost prevented"'s label text plus its `(?)`
  tooltip mark overflowed its own 65px-wide card by 12px, the entire
  remaining page-level overflow. Fixed by giving `StatCard` a real
  `flex: "1 1 140px"` / `minWidth: "140px"` so the row wraps into 2x2 at
  this width instead of cramming 4 cards into one row. Verified live at an
  exact 375px viewport with seeded S3-configured test data (throwaway org,
  deleted after): `document.documentElement.scrollWidth` was 442 before any
  fix, 372 after the flex-row fix alone (chart/Top-IPs row fix only), and
  360 against a 360 `clientWidth` after the StatCard fix, zero overflow.
  Confirmed visually via screenshot: stat cards wrap 2x2, chart and Top
  threat IPs stack vertically.

## [Severity: Low] Manual block shows the raw Pydantic validation string

- **Where**: `/dashboard/ips`, Blocked tab, "Block an IP manually".
- **Steps to reproduce**: Enter `not-an-ip`, click "Block IP".
- **Expected**: Customer-facing copy, for example "Enter a valid public IP
  address."
- **Actual**: The page no longer crashes (the Critical finding is genuinely
  fixed, confirmed: no error boundary, form stays usable), but the inline
  message is the library's own wording, "value is not a valid IPv4 or IPv6
  address". Private and reserved addresses will surface the custom validator's
  message through the same path, so only the type-level failure reads oddly.
- **Suspected file(s)**: `frontend/src/components/dashboard/BlockedIpsTab.tsx`.
- **Fix**: root-caused to the backend, not the frontend. `ManualBlockBody`'s
  custom `reject_unsafe_ip` validator only runs after Pydantic's own built-in
  `IPvAnyAddress` coercion succeeds, so a non-IP-shaped string never reaches
  it, Pydantic's own raw wording surfaces first, with no `"Value error, "`
  prefix for `BlockedIpsTab.tsx`'s existing `extractErrorMessage()` to strip.
  Added a `mode="before"` validator (`reject_malformed_ip`) on the same `ip`
  field in `api/routes/verdicts.py` that pre-checks the string with
  `ipaddress.ip_address()` and raises a customer-facing `ValueError` ("Enter
  a valid public IP address.") before Pydantic's own coercion runs, matching
  the existing validator's message style so the frontend's prefix-stripping
  logic handles it with no frontend change needed. Verified live via the
  dashboard form: `not-an-ip` now shows "Enter a valid public IP address."
  with no crash; re-tested the existing loopback/reserved-IP case
  (`127.0.0.1`) as a regression check, still shows its own correct message
  unchanged.

---

## Verified fixed, re-tested this pass

**Phase 1**

- "Ways to connect" is a standalone section in the right place. Measured section
  order: Hero, Cost calculator, How it works, Detection engine, Ways to connect,
  Pricing. It has a real `h2`, names no cloud provider brands, carries no
  "(planned)" label text, and the dead method is `cursor: not-allowed` with no
  click handler. The abandoned "Platform support" box is gone from
  `HowItWorks.tsx` (confirmed absent from the rendered page).
- Cost-prevented tooltip. `(?)` renders after the label with
  `cursor: help`, `margin-left: 4px`, and the full title text "Estimate only,
  confidence-weighted, using the same assumptions as the homepage cost
  calculator."
- Blinking loading cursor. `LoadingCursor` is used in 9 call sites; the only
  remaining `"Loading…"` literal is the MFA button label at
  `settings/page.tsx:1863`, which the spec explicitly excluded, plus one
  comment. Animation is opacity-only.
- New-row flash. Verified live: inserted a verdict after page load, clicked
  Refresh, and only that one row carried `animation-name: new-row-flash`
  (measured `rgba(42,42,42,0.66)` mid-animation) while all 7 other rows stayed
  `none`. Cleared itself after ~1.2s. No flash on first load.
- Modal entrance animation. All 7 call sites carry it (3 in
  `settings/page.tsx`, 1 each in `BlockedIpsTab`, `PlanCheckoutTrigger`,
  `TeamMembers`, `SessionExpiredModal`). Confirmed live on the delete-account
  modal: panel `modal-panel-in` at 150ms, overlay correctly un-animated,
  movement only with no opacity fade.
- `globals.css` gained exactly the three keyframes, all dashboard-scoped.
- `npx tsc --noEmit` clean. No em dash introduced anywhere in the Phase 1 diff.

**Previous FIXES.md pass**

- Invalid IP no longer crashes the IPs page (see the Low finding above for the
  remaining copy nit).
- Recent threats now sorts by recency: the newest verdict appeared at the top
  immediately after insertion.
- Flag emoji gone from Top threat IPs (renders the null placeholder for an
  unknown country).
- "1 hit" is now correctly singular.
- Cost prevented renders in INR (`₹246.17`) for an `IN` home-country org
  instead of always USD.
- Settings plan description is tier-correct: a `growth` org reads "You're on
  the Growth plan.", not the old hardcoded free-tier sentence.
- `#mfa` anchor now scrolls on client-side navigation (`window.scrollY` 4392
  after clicking "Set up MFA" from `/dashboard`).
- Verdicts tab action gating works for a paid tier (Growth org shows
  "View | Block").
- MFA nudge banner em dash fixed: "Secure your account: enable two-factor
  authentication."
- Mobile overflow resolved on `/dashboard/alerts` and `/dashboard/ips`.

## Not re-tested

Anything needing a live external service or a destructive flow: Razorpay
checkout, real AWS blocking, outbound email, account deletion past the modal,
invite acceptance, password reset, and MFA enrolment. The previous pass's
findings in those areas are marked fixed in commit `023118c` but were not
re-exercised here, per the request to keep this scoped and cheap.

## Counts by severity

High 1, Medium 2, Low 1. Total 4.
