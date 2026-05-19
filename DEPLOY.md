# Clew — Step-by-Step Deployment Guide

This is a linear walkthrough. Do every step in order. Skip nothing the first
time. When it says "open a terminal on your laptop" it means not the SSH session
— it means a separate window on your own machine.

---

## What you will end up with

Two public HTTPS endpoints:
- `https://clewsec.com` — Next.js frontend (marketing + dashboard)
- `https://api.clewsec.com` — FastAPI backend

Four background processes managed by PM2:
- `clew-api` — FastAPI on port 8000 (internal, not public)
- `clew-frontend` — Next.js on port 3000 (internal, not public)
- `clew-worker` — Celery worker (processes customer logs)
- `clew-beat` — Celery beat scheduler (triggers polling every 15 min)

One database (PostgreSQL) and one cache/broker (Redis), both localhost-only.

---

## Phase 1 — AWS Setup (do this before provisioning the server)

### 1.1 Create an IAM user for Clew

IAM (Identity and Access Management) is AWS's permission system. Your server
needs to call two AWS services: SES to send emails, and WAF to block IPs. You
do not use your root AWS account for this. Instead you create a dedicated machine
user called `clew-server` with only those two permissions.

**In the AWS Console:**

1. Search for **IAM** in the top search bar → open it
2. Left sidebar → **Users** → **Create user**
3. Username: `clew-server`
4. On the console access screen: **leave "Provide user access to the AWS
   Management Console" unticked** — this is a machine user, not a person
5. Click Next → choose "Attach policies directly"
6. Search `AmazonSESFullAccess` → tick it
7. Now create a custom WAF policy. Click **Create policy** (opens a new tab):
   - Click the **JSON** tab
   - Replace everything in the box with:
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [{
         "Effect": "Allow",
         "Action": [
           "wafv2:GetIPSet",
           "wafv2:UpdateIPSet"
         ],
         "Resource": "*"
       }]
     }
     ```
   - Click Next → Name: `ClewWAFBlockingPolicy` → **Create policy**
   - Close that tab and go back to the user creation tab
   - Click the refresh icon next to the policy search box
   - Search `ClewWAFBlockingPolicy` → tick it (alongside AmazonSESFullAccess)
8. Click Next → **Create user**

**Get the access keys:**

1. Click the new `clew-server` user → **Security credentials** tab
2. **Create access key** → use case: "Application running outside AWS"
3. You see two values: **Access key ID** and **Secret access key**
4. Copy both into a password manager NOW. The secret is shown once only.
   If you close without saving it you must delete and recreate the key.

These go into your server `.env` as `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY`.

---

### 1.2 Verify your sending domain in SES

SES is AWS's email service. Before it can send mail from your domain it needs
proof you own it.

1. AWS Console → search **SES** → open it
2. Left sidebar → **Verified identities** → **Create identity**
3. Identity type: **Domain**
4. Enter: `clewsec.com` (root domain only, no subdomain)
5. SES shows you DNS records to add — typically three CNAME records
6. Open your domain registrar in a separate tab. Add those CNAME records exactly
   as SES shows them.
7. Back in SES, click the refresh icon after 5–10 minutes. Once it says
   **Verified** you can send from `noreply@clewsec.com` or any other address
   at that domain.

**Important — SES sandbox mode:**

New AWS accounts are in sandbox mode. In sandbox you can only send to email
addresses you have explicitly added as "verified identities" in SES. Real
customers will not receive emails until you leave sandbox.

To request production access:
- SES Console → **Account dashboard** → **Request production access**
- Use case: transactional SaaS. Emails are: OTP verification codes and security
  alert notifications. No bulk marketing. Include that Clew is a B2B product
  where each user triggers at most a few emails per day.
- AWS approves within 24 hours.

You can deploy and test the whole product in sandbox by just adding your own
email as a verified identity. Do production access request in parallel.

---

## Phase 2 — EC2 Server

### 2.1 Launch the instance

**AWS Console → EC2 → Launch instances:**

- **Name:** `clew-production`
- **AMI:** Ubuntu Server 22.04 LTS
  - In the search box type "ubuntu 22.04"
  - Pick the one from Canonical (the official Ubuntu publisher). It says
    "64-bit (x86)" and "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04..."
  - Do NOT pick Ubuntu 24.04 — Node 20 setup scripts are tested on 22.04
- **Instance type:** `t3.small` (2 vCPU, 2 GB RAM, ~$15/month)
- **Key pair:**
  - Click "Create new key pair"
  - Name: `clew-key`
  - Type: RSA, format: .pem
  - Click Create key pair — the `.pem` file downloads to your Downloads folder
  - On your laptop, move and lock it:
    ```bash
    mv ~/Downloads/clew-key.pem ~/.ssh/clew-key.pem
    chmod 400 ~/.ssh/clew-key.pem
    ```
  - `chmod 400` = read-only for you. SSH refuses to use key files that anyone
    else can read.
- **Network settings:** Create a new security group with these inbound rules:

  | Port | Type | Source |
  |---|---|---|
  | 22 | SSH | My IP |
  | 80 | HTTP | Anywhere (0.0.0.0/0) |
  | 443 | HTTPS | Anywhere (0.0.0.0/0) |

  Port 80 must be open even for an HTTPS-only site — Certbot uses HTTP to
  complete the domain ownership challenge before issuing the certificate.

- **Storage:** 20 GB, volume type: **gp3** (always pick gp3 over gp2 — same
  SSD type, cheaper, and you can adjust IOPS independently)

Click **Launch instance**.

---

### 2.2 Allocate a permanent IP (Elastic IP)

Without an Elastic IP, your server gets a new random IP every time it restarts.
Your DNS records would break. An Elastic IP is a static address that stays yours
permanently.

1. EC2 left sidebar → **Elastic IPs** (under "Network & Security")
2. **Allocate Elastic IP address** → Allocate
3. Select the new IP → **Actions** → **Associate Elastic IP address**
4. Instance: select `clew-production` → **Associate**

Write down the IP address. You will use it in DNS and every SSH command.

---

### 2.3 Point DNS at the server

In your domain registrar (wherever you manage `clewsec.com`), add:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | @ | Your Elastic IP | 300 |
| A | api | Your Elastic IP | 300 |

`@` means the root domain (`clewsec.com`). `api` makes `api.clewsec.com`.
Both point at the same server. Nginx will route them to different ports.

TTL 300 = 5 minutes. Keep it short while deploying. Raise to 3600 when stable.

---

## Phase 3 — Server Setup

### 3.1 SSH in for the first time

On your laptop:

```bash
ssh -i ~/.ssh/clew-key.pem ubuntu@YOUR_ELASTIC_IP
```

First connection: SSH asks "Are you sure you want to continue connecting?" → type
`yes`. You are logged in as `ubuntu`. This user is not root but has `sudo` access.
Prefix privileged commands with `sudo`.

---

### 3.2 System packages

Run each block. Total time: about 5 minutes.

```bash
# 1. Update package lists and upgrade pre-installed packages.
#    Always do this first on a fresh server.
sudo apt update && sudo apt upgrade -y
```

```bash
# 2. Python 3.11 (Clew's backend language)
sudo apt install -y python3.11 python3.11-venv python3.11-dev build-essential
```

```bash
# 3. Node.js 20 (required to build and run Next.js)
#    The curl command registers the Node 20 apt repository, then we install it.
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

```bash
# 4. PostgreSQL (the database)
sudo apt install -y postgresql postgresql-contrib
```

```bash
# 5. Redis (Celery's job queue and the rate-limiting store)
sudo apt install -y redis-server
```

```bash
# 6. Nginx (receives all internet traffic and routes it to the right process)
sudo apt install -y nginx
```

```bash
# 7. Certbot (gets free TLS certificates from Let's Encrypt and renews them)
sudo apt install -y certbot python3-certbot-nginx
```

```bash
# 8. PM2 (keeps all four Clew processes running permanently)
sudo npm install -g pm2
```

```bash
# 9. Git
sudo apt install -y git
```

---

### 3.3 Create the PostgreSQL database

PostgreSQL is running but only has a system superuser. You need a dedicated
database and user for Clew.

```bash
sudo -u postgres psql << 'EOF'
CREATE USER clew WITH PASSWORD 'REPLACE_ME_STRONG_PASSWORD';
CREATE DATABASE clew OWNER clew;
GRANT ALL PRIVILEGES ON DATABASE clew TO clew;
EOF
```

Replace `REPLACE_ME_STRONG_PASSWORD` with 20+ random characters. Use a password
manager to generate it. Save it — it goes in `DATABASE_URL` shortly.

Postgres on Ubuntu listens on localhost only. Never open port 5432 in your
security group.

---

### 3.4 Lock Redis to localhost

Redis is running but double-check it cannot accept connections from the internet.

```bash
sudo nano /etc/redis/redis.conf
```

Find this line:
```
bind 127.0.0.1 ::1
```

Make sure it is **not** commented out (no `#` at the start). If it has a `#`,
remove it.

Save: `Ctrl+X` → `Y` → `Enter`

```bash
sudo systemctl restart redis
# Enable auto-start so Redis comes back up after a server reboot
sudo systemctl enable redis
```

---

## Phase 4 — Deploy the Code

### 4.1 Clone the repository

```bash
cd /home/ubuntu
git clone https://github.com/YOUR_GITHUB_USERNAME/abuse.git clew
cd clew
```

---

### 4.2 Create the Python virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` (in the repo root) installs everything: FastAPI, Uvicorn,
SQLAlchemy, Alembic, Celery, Redis client, boto3, Stripe, bcrypt, PyOTP, and
the detection engine's scientific libraries. Takes about 2 minutes.

A virtual environment isolates all packages to this project. You need to run
`source .venv/bin/activate` every time you SSH in and want to run Python
commands manually.

---

### 4.3 Create the backend .env file

This file holds all secrets, never committed to git.

```bash
nano /home/ubuntu/clew/.env
```

Paste this entire block. Every line that says `FILL_IN` must be replaced.

```
# ═══════════════════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════════════════

# Use the password you set in step 3.3 above
DATABASE_URL=postgresql://clew:REPLACE_ME_STRONG_PASSWORD@localhost:5432/clew

# ═══════════════════════════════════════════════════════════════════════════
# REDIS
# ═══════════════════════════════════════════════════════════════════════════

REDIS_URL=redis://localhost:6379/0

# ═══════════════════════════════════════════════════════════════════════════
# AUTH SECRETS
# ═══════════════════════════════════════════════════════════════════════════

# JWT_SECRET signs every login token. If this leaks, every session in the
# system can be forged. Rotate immediately if compromised (all users log out).
# Generate on your laptop: openssl rand -hex 64
JWT_SECRET=FILL_IN

JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# TOTP_ENCRYPTION_KEY encrypts authenticator app secrets stored in the db.
# Generate on your laptop:
#   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOTP_ENCRYPTION_KEY=FILL_IN

# ═══════════════════════════════════════════════════════════════════════════
# URLS
# ═══════════════════════════════════════════════════════════════════════════

FRONTEND_URL=https://clewsec.com

# Leading dot required — lets the auth cookie work across clewsec.com AND
# api.clewsec.com as the same session. Without the dot, setting a cookie on
# api.clewsec.com would be invisible to clewsec.com.
COOKIE_DOMAIN=.clewsec.com

# ═══════════════════════════════════════════════════════════════════════════
# AWS — the clew-server IAM user credentials from Phase 1
# ═══════════════════════════════════════════════════════════════════════════

AWS_ACCESS_KEY_ID=FILL_IN
AWS_SECRET_ACCESS_KEY=FILL_IN
AWS_DEFAULT_REGION=ap-south-1

# ═══════════════════════════════════════════════════════════════════════════
# SES — outbound email
# ═══════════════════════════════════════════════════════════════════════════

SES_FROM_ADDRESS=noreply@clewsec.com
SES_FROM_NAME=Clew Security
# LOG_EMAILS=1 prints emails to the terminal instead of sending (dev only).
# Leave blank in production.
LOG_EMAILS=

# ═══════════════════════════════════════════════════════════════════════════
# CELERY
# ═══════════════════════════════════════════════════════════════════════════

# Worker concurrency = number of parallel log-processing tasks.
# t3.small has 2 vCPU → set 4.
# t3.medium has 2 vCPU → set 4.
# t3.xlarge has 4 vCPU → set 8.
CELERY_CONCURRENCY=4

# ═══════════════════════════════════════════════════════════════════════════
# OAUTH — leave all blank for now, fill when you want social login
# ═══════════════════════════════════════════════════════════════════════════

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=https://api.clewsec.com/auth/google/callback

GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GITHUB_REDIRECT_URI=https://api.clewsec.com/auth/github/callback

MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_REDIRECT_URI=https://api.clewsec.com/auth/microsoft/callback

# ═══════════════════════════════════════════════════════════════════════════
# STRIPE — leave blank until Stripe is approved, add values from the
# "Adding Stripe" section at the bottom of this guide
# ═══════════════════════════════════════════════════════════════════════════

STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_STARTER_INR=
STRIPE_PRICE_STARTER_USD=
STRIPE_PRICE_GROWTH_INR=
STRIPE_PRICE_GROWTH_USD=
STRIPE_PRICE_PRO_INR=
STRIPE_PRICE_PRO_USD=

# ═══════════════════════════════════════════════════════════════════════════
# OPTIONAL
# ═══════════════════════════════════════════════════════════════════════════

# AbuseIPDB enriches threat findings with public IP reputation data.
# Free API key at https://www.abuseipdb.com/register — optional.
ABUSEIPDB_API_KEY=
```

Save: `Ctrl+X` → `Y` → `Enter`

Now lock the file so only your user can read it:
```bash
chmod 600 /home/ubuntu/clew/.env
```

**Generate the two secrets right now.** Open a terminal on your laptop (not the
SSH session) and run:

```bash
# JWT secret (64 hex characters)
openssl rand -hex 64

# TOTP Fernet key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

SSH back into the server and paste both values into the `.env` file:
```bash
nano /home/ubuntu/clew/.env
# Find JWT_SECRET=FILL_IN and TOTP_ENCRYPTION_KEY=FILL_IN, replace them
```

---

### 4.4 Run database migrations

Migrations create all the tables in PostgreSQL. Alembic reads `DATABASE_URL`
automatically from `.env` via `python-dotenv`.

```bash
cd /home/ubuntu/clew
source .venv/bin/activate
alembic upgrade head
```

Expected output — you should see three migrations run:
```
INFO  [alembic.runtime.migration] Running upgrade  -> c957d12130b9, initial schema
INFO  [alembic.runtime.migration] Running upgrade c957d12130b9 -> b4e8f2a1c953, add stripe billing columns
INFO  [alembic.runtime.migration] Running upgrade b4e8f2a1c953 -> e3c1a7f920d4, add mfa backup codes
```

If you see an error like `FATAL: role "clew" does not exist` you skipped
step 3.3. If you see `KeyError: DATABASE_URL` the `.env` file is not in
`/home/ubuntu/clew/.env` or `DATABASE_URL=` line has a typo.

---

### 4.5 Create the frontend .env.local file

The frontend needs two different kinds of env vars:

- `NEXT_PUBLIC_*` vars are baked into the JavaScript bundle sent to the browser.
  Safe to expose. Used for API URLs etc.
- `JWT_SECRET` (no NEXT_PUBLIC prefix) stays on the server only. Next.js reads
  it in the middleware (`proxy.ts`) to verify auth cookies server-side. If this
  is missing or wrong, every protected page redirects to /login even when the
  user is logged in.

```bash
cat > /home/ubuntu/clew/frontend/.env.local << 'EOF'
NEXT_PUBLIC_API_URL=https://api.clewsec.com
NEXT_PUBLIC_SITE_URL=https://clewsec.com

# Must be identical to JWT_SECRET in /home/ubuntu/clew/.env
# Copy and paste the exact same value here
JWT_SECRET=PASTE_SAME_JWT_SECRET_HERE
EOF
```

Replace `PASTE_SAME_JWT_SECRET_HERE` with the JWT_SECRET you generated:
```bash
nano /home/ubuntu/clew/frontend/.env.local
```

---

### 4.6 Build the frontend

```bash
cd /home/ubuntu/clew/frontend
npm install
npm run build
```

`npm run build` compiles all Next.js pages into optimised production assets.
Takes about 1–2 minutes. When done it prints a table of every compiled page.
Any error here is almost always a wrong or missing env var.

---

## Phase 5 — Nginx (traffic routing)

Nginx receives all incoming connections on ports 80/443 and decides where to
send them. Nothing is exposed directly — both FastAPI and Next.js only listen
on localhost.

```bash
sudo nano /etc/nginx/sites-available/clew
```

Paste (replacing `clewsec.com` only if your domain is different):

```nginx
# ─────────────────────────────────────────────────────────
# Next.js frontend: clewsec.com and www.clewsec.com
# ─────────────────────────────────────────────────────────
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

# ─────────────────────────────────────────────────────────
# FastAPI backend: api.clewsec.com
# ─────────────────────────────────────────────────────────
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

Enable the config and remove the default placeholder:

```bash
sudo ln -s /etc/nginx/sites-available/clew /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test — must say "syntax is ok" before you continue
sudo nginx -t

sudo systemctl reload nginx
```

---

## Phase 6 — HTTPS (TLS certificate)

Certbot gets a free 90-day certificate and edits your Nginx config to use it.
It also creates a cron job that renews automatically before expiry.

DNS must be pointing at your server before this works. Verify first:

```bash
ping clewsec.com       # must show YOUR Elastic IP
ping api.clewsec.com   # must show YOUR Elastic IP
```

If either shows a different IP, DNS has not propagated yet. Wait a few minutes
and try again. Do not run Certbot until both are correct.

```bash
sudo certbot --nginx -d clewsec.com -d www.clewsec.com -d api.clewsec.com
```

Certbot prompts:
1. Email address — enter something real (used for expiry warnings)
2. Agree to terms → `A`
3. Share email with EFF → your choice

It then modifies your Nginx config and issues the certificate. When done, test
that auto-renewal works:

```bash
sudo certbot renew --dry-run
# Should say "Congratulations, all simulated renewals succeeded"
```

---

## Phase 7 — Start Processes with PM2

PM2 manages all four Clew processes as persistent services. If a process crashes
it restarts automatically. The `pm2 startup` command makes PM2 itself start on
server reboot, which brings all four processes back.

### 7.1 Create the PM2 config file

```bash
nano /home/ubuntu/clew/ecosystem.config.js
```

Paste this exactly — no changes needed if you followed this guide:

```js
module.exports = {
  apps: [
    // FastAPI backend
    {
      name:        'clew-api',
      cwd:         '/home/ubuntu/clew',
      interpreter: '/home/ubuntu/clew/.venv/bin/python',
      script:      '/home/ubuntu/clew/.venv/bin/uvicorn',
      args:        'api.main:app --host 127.0.0.1 --port 8000 --workers 2',
      env_file:    '/home/ubuntu/clew/.env',
    },

    // Next.js frontend
    {
      name:   'clew-frontend',
      cwd:    '/home/ubuntu/clew/frontend',
      script: 'node_modules/.bin/next',
      args:   'start --port 3000',
      env: {
        NODE_ENV:               'production',
        NEXT_PUBLIC_API_URL:    'https://api.clewsec.com',
        NEXT_PUBLIC_SITE_URL:   'https://clewsec.com',
        // JWT_SECRET is read from .env.local automatically by Next.js at startup
      },
    },

    // Celery worker (processes customer S3 logs, runs the detection engine)
    {
      name:        'clew-worker',
      cwd:         '/home/ubuntu/clew',
      interpreter: '/home/ubuntu/clew/.venv/bin/python',
      script:      '/home/ubuntu/clew/.venv/bin/celery',
      args:        '-A workers.celery_app worker --loglevel=info --concurrency=4',
      env_file:    '/home/ubuntu/clew/.env',
    },

    // Celery beat scheduler (triggers the 15-min poll cycle)
    {
      name:        'clew-beat',
      cwd:         '/home/ubuntu/clew',
      interpreter: '/home/ubuntu/clew/.venv/bin/python',
      script:      '/home/ubuntu/clew/.venv/bin/celery',
      args:        '-A workers.celery_app beat --loglevel=info',
      env_file:    '/home/ubuntu/clew/.env',
      // IMPORTANT: always run exactly ONE instance of clew-beat.
      // If you accidentally run two, every task fires twice —
      // every customer gets polled twice every 15 min.
    },
  ],
};
```

---

### 7.2 Start everything

```bash
cd /home/ubuntu/clew
pm2 start ecosystem.config.js
```

---

### 7.3 Register PM2 as a system service

```bash
# Save the process list so PM2 knows what to start on reboot
pm2 save

# Generate the startup command. PM2 prints a sudo command — copy it exactly.
pm2 startup
```

The `pm2 startup` output looks like:
```
[PM2] To setup the Startup Script, copy/paste the following command:
sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u ubuntu --hp /home/ubuntu
```

Copy and run that entire `sudo env ...` line exactly as printed. It registers
PM2 with systemd so your four processes come back automatically after a reboot.

---

### 7.4 Check everything is running

```bash
pm2 status
```

You should see a table with four rows, all showing status `online`:

```
┌─────┬────────────────┬─────────────┬──────┬───────────┐
│ id  │ name           │ mode        │ pid  │ status    │
├─────┼────────────────┼─────────────┼──────┼───────────┤
│ 0   │ clew-api       │ fork        │ ...  │ online    │
│ 1   │ clew-frontend  │ fork        │ ...  │ online    │
│ 2   │ clew-worker    │ fork        │ ...  │ online    │
│ 3   │ clew-beat      │ fork        │ ...  │ online    │
└─────┴────────────────┴─────────────┴──────┴───────────┘
```

If any show `errored`, check its logs:
```bash
pm2 logs clew-api --lines 50
pm2 logs clew-worker --lines 50
```

---

## Phase 8 — Firewall

Adds a second layer of protection on top of the EC2 security group:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Do NOT open 5432 (Postgres) or 6379 (Redis). They stay localhost-only.

---

## Phase 9 — Verify Everything Works

Work through every item. Do not skip.

### Quick server tests (in the SSH session)

```bash
# API is up and responds directly (bypasses Nginx)
curl http://localhost:8000/health
# Expected: {"status":"ok"}

# Frontend is up (bypasses Nginx)
curl -s http://localhost:3000 | head -5
# Expected: some HTML

# Redis is alive
redis-cli ping
# Expected: PONG

# Database migrations are current
cd /home/ubuntu/clew && source .venv/bin/activate && alembic current
# Expected: e3c1a7f920d4 (head)

# All four processes running
pm2 status
```

### Browser tests

Open each URL in your browser:

| URL | Expected |
|---|---|
| `https://clewsec.com` | Marketing homepage, padlock visible |
| `https://api.clewsec.com/health` | `{"status":"ok"}` |
| `http://clewsec.com` | Redirects to https:// |
| `https://clewsec.com/register` | Registration form loads |

### Auth test

1. Go to `https://clewsec.com/register` and create an account
2. Check your inbox — verification email should arrive within 30 seconds
   (if it doesn't, check `pm2 logs clew-api` for SES errors)
3. Enter the OTP code
4. You reach the dashboard
5. Log out → redirects to `/login`
6. Log back in → reaches dashboard again

---

## Day-to-Day Commands

```bash
# Check all process statuses
pm2 status

# Watch logs live (Ctrl+C to stop)
pm2 logs clew-api
pm2 logs clew-worker
pm2 logs clew-beat

# See last 100 lines
pm2 logs clew-api --lines 100

# Restart one process (e.g. after changing .env)
pm2 restart clew-api

# Restart everything
pm2 restart all

# Connect to the database interactively
psql postgresql://clew:YOUR_DB_PASSWORD@localhost/clew
# Inside psql:
#   \dt           — list all tables
#   \q            — quit

# Check disk space
df -h

# Check memory
free -h

# CPU activity
top
```

---

## Pushing Code Updates

Every time you push a change to GitHub:

```bash
cd /home/ubuntu/clew
git pull

# If requirements.txt changed:
source .venv/bin/activate
pip install -r requirements.txt

# If a new database migration was added:
source .venv/bin/activate
alembic upgrade head

# If frontend code changed:
cd frontend
npm run build
cd ..

# Restart what changed:
pm2 restart clew-api               # API or workers code
pm2 restart clew-frontend          # frontend (after npm run build)
pm2 restart clew-worker clew-beat  # Celery tasks
```

When in doubt: `pm2 restart all`

---

## Upgrading the Server

Two minutes downtime. No data loss. Same IP, same DNS, same certificates.

1. EC2 → Instances → tick `clew-production`
2. **Instance state → Stop instance** → confirm
3. Wait for "Stopped" (30 seconds)
4. **Actions → Instance settings → Change instance type** → pick new type
5. **Instance state → Start instance**
6. SSH back in:
   ```bash
   ssh -i ~/.ssh/clew-key.pem ubuntu@YOUR_ELASTIC_IP
   pm2 resurrect
   pm2 status
   ```

| Type | vCPU | RAM | ~Cost/mo | When |
|---|---|---|---|---|
| t3.small | 2 | 2 GB | $15 | Up to ~5-10 customers |
| t3.medium | 2 | 4 GB | $30 | First few paying customers |
| t3.large | 2 | 8 GB | $60 | Heavy log volumes |
| t3.xlarge | 4 | 16 GB | $120 | 30+ customers |

After upgrading to t3.xlarge, also update `CELERY_CONCURRENCY` in `.env`
to 8, then `pm2 restart clew-worker`.

---

## Testing Tier Features Without Stripe

The upgrade buttons in the dashboard Settings page send the user to Stripe
checkout. Until Stripe keys are configured they return an error. The product
works on `free` tier — to test Growth/Pro features on your own account:

```bash
psql postgresql://clew:YOUR_DB_PASSWORD@localhost/clew
```

Inside psql:
```sql
-- Check current tier
SELECT email, tier FROM clients WHERE email = 'your@email.com';

-- Set to growth
UPDATE clients SET tier = 'growth' WHERE email = 'your@email.com';

\q
```

Valid values: `free`, `starter`, `growth`, `pro`

---

## Customer Onboarding — S3 Access

When a customer signs up and wants Clew to analyse their logs, they:

1. Go to Settings in the dashboard
2. Paste their **S3 bucket name** (where AWS API Gateway writes their access logs)
3. In their own AWS account, add a bucket policy to that bucket:

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

Where `YOUR_CLEW_ACCOUNT_ID` is the 12-digit number shown in the top-right
corner of your AWS console. You give this to customers during onboarding.

That is all. You do not touch their AWS account. They grant one read-only door
to one bucket and Clew starts polling it every 15 minutes.

---

## Adding Stripe Later

The code is complete. Add keys when your company registration is approved.

### Step 1 — Get keys

Stripe Dashboard → Developers → API keys → copy **Secret key** (`sk_live_...`)

### Step 2 — Create products and prices

One product per tier, two prices each (monthly INR and monthly USD):

| Tier | USD | INR |
|---|---|---|
| Starter | $99/mo | Rs.6,999/mo |
| Growth | $249/mo | Rs.14,999/mo |
| Pro | $449/mo | Rs.29,999/mo |

Each price has an ID like `price_1ABC...`. You need six IDs total.

### Step 3 — Register the webhook

Stripe Dashboard → Developers → Webhooks → **Add endpoint**:
- URL: `https://api.clewsec.com/billing/webhook`
- Events: `checkout.session.completed`, `customer.subscription.updated`,
  `customer.subscription.deleted`

Copy the **Signing secret** (`whsec_...`).

### Step 4 — Add to .env

```bash
nano /home/ubuntu/clew/.env
```

Fill in the currently-blank Stripe lines:

```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_STARTER_INR=price_...
STRIPE_PRICE_STARTER_USD=price_...
STRIPE_PRICE_GROWTH_INR=price_...
STRIPE_PRICE_GROWTH_USD=price_...
STRIPE_PRICE_PRO_INR=price_...
STRIPE_PRICE_PRO_USD=price_...
```

```bash
pm2 restart clew-api
```

### Step 5 — Test with test keys first

Use `sk_test_...` and a test mode webhook (`whsec_...` from a test endpoint).
Stripe's test card: `4242 4242 4242 4242`, any future expiry, any CVC.

Go through a full checkout in the dashboard, then verify:

```bash
psql postgresql://clew:YOUR_DB_PASSWORD@localhost/clew \
  -c "SELECT email, tier, stripe_subscription_id FROM clients WHERE email = 'your@email.com';"
```

Once confirmed working, swap in the live keys.

---

## Adding OAuth Later

When you want social login (Google/GitHub/Microsoft). The backend is ready —
just needs keys.

**Google:**
1. console.cloud.google.com → APIs & Services → Credentials → Create OAuth 2.0
   Client ID → Web application
2. Authorised redirect URI: `https://api.clewsec.com/auth/google/callback`
3. Copy Client ID + Secret into `.env` → `pm2 restart clew-api`

**GitHub:**
1. github.com → Settings → Developer settings → OAuth Apps → New OAuth App
2. Callback URL: `https://api.clewsec.com/auth/github/callback`
3. Copy Client ID → Generate Client Secret → add both to `.env` →
   `pm2 restart clew-api`

**Microsoft (for customers with Azure AD / Office 365):**
1. portal.azure.com → Microsoft Entra ID → App registrations → New registration
2. Account types: "Accounts in any organizational directory and personal
   Microsoft accounts"
3. Redirect URI: Web → `https://api.clewsec.com/auth/microsoft/callback`
4. After creating: Certificates & secrets → New client secret → copy it
5. Overview page → copy Application (client) ID
6. Add both to `.env` → `pm2 restart clew-api`
