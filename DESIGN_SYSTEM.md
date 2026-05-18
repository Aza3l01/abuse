# Clew — Design System & Philosophy

## Philosophy

Sharp, precise, no softness. Every design decision reinforces the same message:
this is a serious tool built for people who care about what is happening in their
infrastructure. Nothing rounded, nothing friendly, nothing that looks like a
consumer app.

The aesthetic is consistent across every touchpoint: typewriter font for logo geist sans for text, black and white, square corners, hard borders. When a CTO lands on the site or opens the dashboard it should feel like a terminal, not a SaaS marketing page.

This is deliberate and the opposite of current SaaS trends. Everything in
2024-2025 is pill-shaped buttons, 12px border radius, soft gradients. Clew goes
the other direction. That contrast is the identity.

---

## Color

Two colors. No accent. No gradients.

```css
:root {
  --color-bg:           #F5F5F5;
  --color-surface:      #EBEBEB;
  --color-border:       #D0D0D0;
  --color-text:         #0D0D0D;
  --color-text-muted:   #5A5A5A;
}

[data-theme="dark"] {
  --color-bg:           #0D0D0D;
  --color-surface:      #1A1A1A;
  --color-border:       #2A2A2A;
  --color-text:         #F5F5F5;
  --color-text-muted:   #888888;
}
```

Never use pure #000000 or pure #FFFFFF. The near-extremes above are sharper
on screen and less harsh on the eye.

**Functional colors (dashboard data only, not brand colors):**

```css
--color-critical: #E53E3E;
--color-high:     #DD6B20;
--color-medium:   #D69E2E;
--color-low:      #38A169;
--color-info:     #3182CE;
```

These appear only inside the product where they communicate data. Never on the
marketing site. Never in the logo or any brand asset.

---

## Typography

Two fonts. No exceptions.

### Courier Prime
**Role:** Brand identity, logo, hero headings, display text, any large text
that needs to feel like the brand.

**Source:** Google Fonts
```css
@import url('https://fonts.googleapis.com/css2?family=Courier+Prime:wght@400;700&display=swap');
```

**In Next.js:**
```jsx
import { Courier_Prime } from 'next/font/google'

const courierPrime = Courier_Prime({
  weight: ['400', '700'],
  subsets: ['latin'],
  variable: '--font-courier',
})
```

**Use for:**
- Logo wordmark
- Hero headline on landing page
- Large display text on marketing site
- Section headings where brand weight is needed

**Never use for:**
- Body copy
- Dashboard UI text
- Buttons
- Labels
- Anything below 24px (hairline serifs lose legibility)

---

### Geist Sans
**Role:** All functional UI text. Everything inside the product. Body copy on
the marketing site below the hero.

**Source:** Built into Next.js 14, no external dependency needed.

```jsx
import { GeistSans } from 'geist/font/sans'
import { GeistMono } from 'geist/font/mono'
```

**Use for:**
- Navigation
- Body copy
- Dashboard text
- Buttons
- Labels
- Form elements
- Everything under 24px

**Geist Mono** (the mono variant) is used for:
- IP addresses
- Timestamps
- Code values
- Any data that benefits from monospace alignment in the dashboard

---

### Loading both in Next.js layout

```tsx
// app/layout.tsx
import { GeistSans } from 'geist/font/sans'
import { GeistMono } from 'geist/font/mono'
import { Courier_Prime } from 'next/font/google'

const courierPrime = Courier_Prime({
  weight: ['400', '700'],
  subsets: ['latin'],
  variable: '--font-courier',
})

export default function RootLayout({ children }) {
  return (
    <html
      className={`
        ${GeistSans.variable}
        ${GeistMono.variable}
        ${courierPrime.variable}
      `}
    >
      <body>{children}</body>
    </html>
  )
}
```

### Tailwind font config

```js
// tailwind.config.js
theme: {
  extend: {
    fontFamily: {
      brand: ['var(--font-courier)', 'Courier New', 'monospace'],
      sans:  ['var(--font-geist-sans)', 'system-ui', 'sans-serif'],
      mono:  ['var(--font-geist-mono)', 'Courier New', 'monospace'],
    }
  }
}
```

---

## Geometry and Shape

90 degree corners everywhere. No exceptions.

```css
--radius: 0px;
```

**What this means in practice:**

- Buttons: fully square, no border radius
- Cards: square corners, 1px border
- Input fields: square corners
- Modals: square corners
- Badges: square, not pill-shaped
- Charts: override Tremor defaults to remove rounding

No soft shadows. Use borders instead:

```css
/* Do this */
border: 1px solid var(--color-border);

/* Not this */
box-shadow: 0 4px 12px rgba(0,0,0,0.1);
```

Shadows feel soft. Borders feel precise. Borders are correct for this product.

---

## Buttons

```css
/* Primary button */
background: var(--color-text);
color: var(--color-bg);
border: 1px solid var(--color-text);
border-radius: 0;
padding: 8px 16px;

/* Primary hover: invert */
background: var(--color-bg);
color: var(--color-text);

/* Secondary button */
background: transparent;
color: var(--color-text);
border: 1px solid var(--color-border);
border-radius: 0;

/* Secondary hover */
border-color: var(--color-text);
```

No opacity changes on hover. Always invert or increase border contrast.

---

## Layout Principles

**Borders over whitespace for section separation.**
Hard 1px horizontal lines between sections rather than whitespace gaps.

**Tight deliberate spacing.**
Sharp corners with loose padding looks unresolved. Sharp corners with tight
padding looks intentional. Use an 8px base unit.

**Full width section dividers.**
```css
border-top: 1px solid var(--color-border);
```

**Tables over cards for data.**
The alert feed, verdict list, and IP tables are table layouts, not card grids.
Tables reinforce the precision aesthetic and are more readable for security data.

**Dark mode default.**
The dashboard defaults to dark mode. Security dashboards belong in dark mode.
The marketing site offers both and respects system preference.

---

## Logo

### Wordmark
The logo is the word "clew" in Courier Prime, lowercase. No icon mark. No
symbol. Just the wordmark.

### Files

```
public/
  favicon.ico              # 32x32, just "c", legacy fallback
  favicon.svg              # just "c", scalable, modern browsers
  apple-touch-icon.png     # 180x180 square version
  logo-wordmark.svg        # "clew" on transparent, currentColor
  logo-wordmark-black.png  # #0D0D0D text, for email/external use
  logo-wordmark-white.png  # #F5F5F5 text, for dark external contexts
```

### Theme switching with SVG

The wordmark SVG uses `currentColor` for the text fill. No background.
Transparent. The page background shows through.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 48">
  <text
    fill="currentColor"
    font-family="Courier Prime, Courier New, monospace"
    font-size="40"
    font-weight="400"
    y="40">clew</text>
</svg>
```

In CSS, the logo color inherits from the theme:

```css
.logo {
  color: var(--color-text);
}
```

Dark mode: text becomes #F5F5F5 automatically.
Light mode: text becomes #0D0D0D automatically.
One file handles both. No JavaScript required.

### Where each file is used

| Context | File |
|---|---|
| Nav bar | logo-wordmark.svg |
| Footer | logo-wordmark.svg |
| Browser tab | favicon.svg + favicon.ico |
| iOS home screen | apple-touch-icon.png |
| Email signature | logo-wordmark-black.png |
| LinkedIn profile | logo-wordmark-white.png (on dark banner) |
| Open Graph / link preview | og-image.png (separate, designed asset) |

---

## Dashboard Specific

**Tremor overrides:**
Tremor is used for charts and data components. Override its defaults to match
the sharp aesthetic:

```css
/* Remove rounding from Tremor bar charts */
.tremor-BarChart-bar {
  rx: 0;
  ry: 0;
}

/* Override Tremor card rounding */
.tremor-Card-root {
  border-radius: 0 !important;
  border: 1px solid var(--color-border);
  box-shadow: none;
}
```

**Data display:**
- IP addresses: Geist Mono
- Timestamps: Geist Mono
- Threat type labels: Geist Sans, uppercase, letter-spaced
- Severity badges: square, functional color background, white text

**Severity badge colors:**
```
CRITICAL  background: #E53E3E  text: #FFFFFF
HIGH      background: #DD6B20  text: #FFFFFF
MEDIUM    background: #D69E2E  text: #FFFFFF
LOW       background: #38A169  text: #FFFFFF
```

---

## CSS Variables — Full Reference

```css
:root {
  /* Color */
  --color-bg:           #F5F5F5;
  --color-surface:      #EBEBEB;
  --color-border:       #D0D0D0;
  --color-text:         #0D0D0D;
  --color-text-muted:   #5A5A5A;

  /* Functional (data only) */
  --color-critical:     #E53E3E;
  --color-high:         #DD6B20;
  --color-medium:       #D69E2E;
  --color-low:          #38A169;
  --color-info:         #3182CE;

  /* Shape */
  --radius:             0px;

  /* Spacing base unit */
  --unit:               8px;

  /* Typography */
  --font-brand:         'Courier Prime', 'Courier New', monospace;
  --font-sans:          'Geist Sans', system-ui, sans-serif;
  --font-mono:          'Geist Mono', 'Courier New', monospace;
}

[data-theme="dark"] {
  --color-bg:           #0D0D0D;
  --color-surface:      #1A1A1A;
  --color-border:       #2A2A2A;
  --color-text:         #F5F5F5;
  --color-text-muted:   #888888;
}
```

---

## What This System Is Not

No gradients. No blur effects. No glassmorphism. No rounded corners anywhere.
No drop shadows. No accent colors on the marketing site. No animations beyond
a simple 150ms color transition on interactive elements. No illustrations.
No emoji in UI. No decorative elements that do not carry information.
NO em dash

Every element either communicates something or gets removed.
