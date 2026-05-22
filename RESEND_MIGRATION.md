# Resend Migration + HTML Email Templates

Replacing AWS SES with Resend and upgrading all transactional emails from
plain text to styled HTML using the Clew design system.

---

## Your actions (before touching any code)

### 1. Create Resend account
1. Go to https://resend.com → sign up (free, no approval process)
2. Free tier: 3,000 emails/month, 100/day — more than enough for launch

### 2. Verify your sending subdomain
Resend recommends sending from a subdomain (e.g. `mail.clewsec.com`) rather than
your root domain. This isolates email reputation — if any sending issue occurs,
it cannot affect your main domain's deliverability for normal business email.

1. Dashboard → **Domains** → **Add Domain** → enter `email.clewsec.com`
2. Resend shows you DNS records (DKIM TXT records + optionally SPF/DMARC)
3. Add them in Route 53 → Hosted zones → clewsec.com → Create record for each
4. Click **Verify** — usually confirms within a few minutes
5. Status must show **Verified** before you send

All emails will now come from `noreply@email.clewsec.com` — this is correct and
professional. The recipient sees "Clew Security" as the sender name.

### 3. Create an API key
1. Dashboard → **API Keys** → **Create API Key**
2. Name: `clew-production`
3. Permission: **Full access**
4. Copy the key — starts with `re_` — it is shown once only
5. Add it to your `.env` on the server (see Step 1 in code changes below)

### 4. Remove the old SES verified identity (optional but tidy)
- SES → Identities → delete `clewsec.com` identity once Resend is live
- IAM → remove `AmazonSESFullAccess` policy from the `clew-server` user (keep WAF policy)

---

## Code changes

### Step 1 — `.env` (local + server)

Add:
```
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
```

Remove the SES block (no longer needed):
```
# Remove these:
# SES_FROM_ADDRESS=noreply@clewsec.com
# SES_FROM_NAME=Clew Security
```

The from address is now hardcoded as `noreply@mail.clewsec.com` (subdomain —
see domain setup above). No env var needed since it never changes.

---

### Step 2 — `requirements.txt`

Add:
```
resend==2.10.0
```

`boto3` stays — still used by S3 reader and WAF blocker.

---

### Step 3 — `api/auth_utils.py` — replace SES call

**Remove:**
```python
import boto3
from botocore.exceptions import ClientError
...
SES_FROM_ADDRESS = os.environ.get("SES_FROM_ADDRESS", "noreply@example.com")
SES_FROM_NAME    = os.environ.get("SES_FROM_NAME", "Clew")
AWS_REGION       = os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")
```

**Add:**
```python
import resend

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
FROM_ADDRESS   = "Clew Security <noreply@email.clewsec.com>"
```

**New `send_email()` using the Python Resend SDK:**
```python
def send_email(to: str, subject: str, body_text: str, body_html: str | None = None) -> bool:
    try:
        if os.environ.get("LOG_EMAILS", "").lower() in ("1", "true", "yes"):
            print(f"\n{'='*60}")
            print(f"[EMAIL] To: {to}")
            print(f"[EMAIL] Subject: {subject}")
            print(f"[EMAIL] Body:\n{body_text}")
            print(f"{'='*60}\n")
            return True

        resend.api_key = RESEND_API_KEY
        params: resend.Emails.SendParams = {
            "from":    FROM_ADDRESS,
            "to":      [to],
            "subject": subject,
            "text":    body_text,
            "html":    body_html or f"<pre>{body_text}</pre>",
        }
        resend.Emails.send(params)
        return True
    except Exception:
        return False
```

The function signature stays identical — all callers (`send_verification_email`,
`send_password_reset_email`, etc.) are unchanged.

---

### Step 4 — `api/auth_utils.py` — add HTML templates

Six emails get HTML bodies. All share a single layout wrapper:

**Layout:** white card on light grey background, square corners, 1px `#D0D0D0`
border, Courier Prime for the heading, system-ui for body. Light mode only for
email (dark mode in email clients is unreliable — we use near-extremes not pure
black/white so it reads well in forced-dark too).

**Email templates to build:**

| Function | Subject | Key content |
|---|---|---|
| `send_verification_email` | Verify your Clew account | 6-digit code in large monospace, 15-min expiry note |
| `send_password_reset_email` | Reset your Clew password | 6-digit code in large monospace, 15-min expiry note |
| `send_password_changed_email` | Your password was changed | Security notice, support link |
| `send_oauth_linked_email` | {Provider} sign-in linked | Which provider, security notice |
| `send_mfa_enabled_email` | Two-factor authentication enabled/disabled | Security notice |
| `send_alert_email` *(new — currently in workers/tasks/send_alerts.py)* | Threat detected: {severity} | IP, threat type, severity badge, confidence, link to dashboard |

The alert email is the most important one — it's what customers actually see
regularly and it needs to look like it came from a competent security company.

---

### Step 5 — `workers/tasks/send_alerts.py` — pass HTML to send_email

Currently `send_alert_email` calls `send_email()` with plain text only.
Update it to also pass `body_html` using the new alert template.

---

## HTML email design spec

Email HTML must use **inline CSS only** — Gmail strips `<style>` blocks.

### Colour values (hardcoded in email — no CSS variables)
```
Background:    #F5F5F5
Card bg:       #EBEBEB  
Border:        #D0D0D0
Text:          #0D0D0D
Text muted:    #5A5A5A
Critical:      #E53E3E
High:          #DD6B20
Medium:        #D69E2E
Low:           #38A169
```

### Layout structure
```
─────────────────────────────────  ← outer div, bg #F5F5F5, padding 40px 24px
  CLEW                             ← Courier Prime 700, 16px, #0D0D0D, margin-bottom 32px
  ┌─────────────────────────────┐
  │  {Heading}                  │  ← Courier Prime 700, 18px
  │                             │  ← card: bg #EBEBEB, border 1px #D0D0D0, padding 32px
  │  {Body paragraphs}          │  ← system-ui 14px, #0D0D0D, line-height 1.6
  │                             │
  │  ┌─────────────────────┐    │  ← code block (for OTP codes):
  │  │  1 2 3 4 5 6        │    │    bg #F5F5F5, border 1px #D0D0D0,
  │  └─────────────────────┘    │    Courier New 32px 700, text-align center
  │                             │
  │  [Primary button]           │  ← bg #0D0D0D, color #F5F5F5, padding 12px 24px,
  │                             │    system-ui 14px 600, no border-radius, no shadow
  └─────────────────────────────┘
  
  Security notice text           ← system-ui 12px, #5A5A5A
  © 2026 Clew Security           ← system-ui 12px, #5A5A5A
─────────────────────────────────
```

### Alert email additions
The alert email includes a severity badge before the body:

```
  ┌──────────┐
  │ CRITICAL │   ← bg #E53E3E (or colour for severity), color #FFF,
  └──────────┘     system-ui 11px 700, uppercase, letter-spacing 0.07em,
                   padding 4px 8px, no border-radius
```

Followed by: IP address (Courier New, monospace), threat type, confidence
percentage, and a button linking to `https://clewsec.com/dashboard`.

---

## Files changed summary

| File | Change |
|---|---|
| `.env` | Add `RESEND_API_KEY`, remove SES vars |
| `requirements.txt` | Add `resend==2.10.0` |
| `api/auth_utils.py` | Replace boto3/SES with Resend SDK; add HTML templates for all 5 auth emails |
| `workers/tasks/send_alerts.py` | Pass `body_html` to `send_email()` using new alert HTML template |

---

## Deployment steps (after code is ready)

On the EC2 server:
```bash
cd ~/abuse
git pull
pip install -r requirements.txt     # installs resend package
# Add RESEND_API_KEY to /home/ubuntu/abuse/.env on the server
pm2 restart clew-api
pm2 restart clew-worker
```

## Testing

1. Set `LOG_EMAILS=1` locally — confirm all 6 email functions print correctly
2. Set `LOG_EMAILS=` (blank) with a real `RESEND_API_KEY` — register a test account,
   check inbox for the verification email
3. Trigger a password reset — check inbox
4. Manually call `send_alert_email` from a test script — check inbox
5. Check Resend dashboard → **Logs** — all sends should show status `Delivered`
