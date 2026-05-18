# Product Context — Clew

> **Product name:** Clew  
> **Development codename:** abuse

## What This Is

A B2B SaaS product that monitors API gateway logs for abuse and attack patterns,
detects threats using a multi-agent AI engine, blocks malicious traffic via AWS WAF
or Cloudflare, and surfaces findings through a web dashboard. Target clients are
Series A/B SaaS companies and SMBs with APIs and no dedicated security team.
Zero-integration positioning: client gives read-only S3 access to their logs, no
code changes, no proxy, no SDK required.

---

## What Already Exists

A research prototype (`engine`, separate repo, do not touch) validated on four
datasets. It is a Python multi-agent detection system that reads CSV files via CLI
and outputs JSON. The detection logic is proven and will be adapted, not rewritten.

Agents in the research prototype:
- VolumeAgent (IsolationForest, detects DoS/DDoS)
- TemporalAgent (FFT + CUSUM, detects bot periodicity and off-hours patterns)
- AuthAgent (detects brute force and credential stuffing)
- PayloadAgent (detects SQL injection, XSS, path traversal)
- SequenceAgent (detects endpoint enumeration and multi-step abuse)
- GeoIPAgent (graph-based, detects geo anomalies)
- KnowledgeAgent (cross-session pattern memory)
- MetaAgentOrchestrator (weighted fusion, XGBoost stacking, conflict resolution)
- SharedMemory (STM + LTM + EvidenceBoard)
- ToolRegistry (4 tools)
- Optional LLM integration via Ollama (qwen2.5:7b, OpenAI-compatible API)

---

## What Needs To Be Built (everything below is new)

1. S3 log ingestion layer (read real AWS API Gateway/ALB logs instead of CSVs)
2. PostgreSQL persistence (verdicts, client configs, LTM storage)
3. Redis (STM layer replacement + Celery broker)
4. Celery task scheduler (run engine per client on a schedule)
5. FastAPI backend (REST API the dashboard consumes)
6. AWS WAF v2 + Cloudflare blocking integrations
7. Next.js frontend (marketing site + authenticated client dashboard, same app)
8. JWT authentication (per client)
9. Email alerts via AWS SES
10. Nginx + PM2 deployment on a single EC2 instance

---

## Tech Stack

| Layer | Choice |
|---|---|
| Engine | Python 3.11 (adapted from research) |
| API | FastAPI + Uvicorn |
| Task queue | Celery + Redis |
| Database | PostgreSQL via SQLAlchemy + Alembic |
| Cache / STM | Redis |
| Frontend | Next.js 14 (App Router) + Tailwind + Tremor |
| Auth | JWT (python-jose), httpOnly cookies |
| Blocking | boto3 WAF v2 + Cloudflare Python SDK |
| Alerts | AWS SES via boto3 |
| Deployment | EC2 t3.small + Nginx + PM2 + Let's Encrypt |
| DNS | Namecheap → EC2 Elastic IP |
| Local dev | Docker Compose (postgres + redis only) |

---

## Folder Structure

```
[product]/
├── engine/
│   ├── agents/              # adapted agents — no CSV deps, accept log dicts
│   ├── coordinator/         # MetaAgentOrchestrator
│   ├── ingestion/
│   │   ├── s3_reader.py     # reads new entries from client S3 bucket
│   │   ├── apigw_parser.py  # AWS API Gateway access log format
│   │   ├── alb_parser.py    # ALB log format
│   │   └── normalizer.py    # normalizes any format to internal schema
│   ├── memory/              # SharedMemory backed by PostgreSQL + Redis
│   └── schemas.py           # Pydantic models for internal log schema
│
├── api/
│   ├── main.py              # FastAPI app, CORS, middleware
│   ├── auth.py              # JWT creation and validation
│   ├── deps.py              # get_db, get_current_client dependencies
│   └── routes/
│       ├── verdicts.py      # GET /verdicts with filters and pagination
│       ├── dashboard.py     # GET /dashboard/summary stats
│       ├── clients.py       # client config CRUD
│       └── auth.py          # POST /auth/login, /auth/logout
│
├── workers/
│   ├── celery_app.py        # Celery config, broker = Redis
│   ├── beat.py              # periodic schedule per active client
│   └── tasks/
│       ├── process_logs.py  # S3 read → engine → write verdicts
│       ├── send_alerts.py   # SES email on critical verdicts
│       └── push_blocks.py   # WAF or Cloudflare block on high-confidence threat
│
├── blocking/
│   ├── aws_waf.py           # update IP sets via boto3 wafv2
│   └── cloudflare.py        # push firewall rules via Cloudflare API
│
├── db/
│   ├── models.py            # SQLAlchemy ORM models
│   ├── session.py           # DB session factory
│   └── migrations/          # Alembic migration files
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx                   # marketing homepage
│   │   │   ├── pricing/page.tsx
│   │   │   ├── login/page.tsx
│   │   │   └── dashboard/
│   │   │       ├── page.tsx               # overview, stats, cost counter
│   │   │       ├── alerts/page.tsx        # live alert feed
│   │   │       ├── ips/page.tsx           # IP intelligence, history
│   │   │       └── settings/page.tsx      # S3 config, alert prefs, IAM guide
│   │   └── components/
│   │       ├── marketing/                 # homepage, nav, pricing cards
│   │       └── dashboard/                 # tremor charts, verdict tables, stat cards
│   └── package.json
│
├── tests/
├── docker/
│   ├── docker-compose.yml   # local dev: postgres + redis
│   └── nginx.conf
├── .env.example
└── requirements.txt
```

---

## Internal Log Schema

Every log format is normalized into this dict before any agent sees it.
This is the contract between ingestion and the engine.

```python
{
    "timestamp": "2024-01-15T14:23:01Z",   # ISO-8601 UTC
    "ip":        "203.0.113.42",
    "method":    "GET",
    "endpoint":  "/api/v1/users",
    "status":    200,
    "response_size": 1240,                  # bytes
    "latency":   45,                        # milliseconds
    "user_agent": "python-requests/2.28",
    "client_id": "uuid-string"
}
```

---

## Database Models (core tables)

**clients**
id, email, password_hash, company_name, s3_bucket, s3_prefix, log_format,
aws_region, waf_ip_set_id, cloudflare_zone_id, cloudflare_token,
alert_email, tier (starter/growth/pro), last_processed_key, created_at

**verdicts**
id, client_id, timestamp, ip, method, endpoint, threat_type, severity
(low/medium/high/critical), confidence (0-1), agents_triggered (array),
explanation (text), blocked (bool), cost_prevented (float), created_at

**ip_memory**
id, client_id, ip, first_seen, last_seen, total_requests, threat_count,
risk_score, geo_country, notes

**alerts_sent**
id, client_id, verdict_id, channel (email/slack), sent_at, status

Every query is filtered by client_id. No client ever sees another client's data.

---

## Data Flow

```
Celery beat fires every 15-30 min per active client
    ↓
process_logs task runs
    ↓
s3_reader reads new log entries since last_processed_key
    ↓
parser normalizes entries to internal schema
    ↓
engine agents process the batch in parallel
    ↓
MetaAgentOrchestrator produces verdicts
    ↓
verdicts written to PostgreSQL
    ↓
if confidence > threshold AND tier = growth/pro → push_blocks fires (WAF/Cloudflare)
if severity = critical → send_alerts fires (SES email)
    ↓
dashboard reads verdicts via FastAPI → displayed in Next.js
```

---

## URL Structure

```
[domain]/                   → marketing homepage (Next.js, public)
[domain]/pricing            → pricing page (public)
[domain]/login              → auth page (public)
[domain]/dashboard          → overview dashboard (protected, JWT required)
[domain]/dashboard/alerts   → alert feed (protected)
[domain]/dashboard/ips      → IP intelligence (protected)
[domain]/dashboard/settings → client config, S3 setup guide (protected)
api.[domain]/               → FastAPI (all API routes)
```

Nginx on EC2 routes: `api.[domain]/*` → FastAPI port 8000,
everything else → Next.js port 3000.

---

## Blocking: How It Works

There are three architecturally distinct approaches to blocking, in increasing
order of integration cost and speed:

**Approach 1 — WAF rule injection** *(what Clew uses in v1)*
Clew detects from logs, then automatically pushes a block rule to the client's
existing WAF (AWS WAF IP set, Cloudflare Firewall Rule, or nginx deny directive).
No new infrastructure required on the client side. Detection stays log-only.
Latency to block: 5–30 seconds (detection cycle time + rule push).
Acceptable for persistent attacks; not suited for flash attacks.
This is the lowest integration cost and what Growth/Pro clients get.

**Approach 2 — Blocklist sidecar** *(future roadmap)*
Clew maintains a Redis-backed blocklist. A small gateway plugin (nginx module,
Kong plugin, or AWS Lambda authorizer) does a single Redis lookup per request —
binary, sub-1ms. Once Clew's detection fires it writes to Redis; all subsequent
requests from that IP are blocked synchronously by the plugin, not Clew.
Detection is async and smart; enforcement is a dumb fast lookup.
This is how Signal Sciences (Fastly) and similar products work.
Requires the client to install a small plugin — higher integration cost.

**Approach 3 — Inline reverse proxy** *(not in v1, highest cost)*
Clew sits in the request path. Unknown IPs pass through while analysis runs in
parallel. Once flagged, blocks immediately with zero subsequent latency.
Adds ~50–100ms before a threat is confirmed. Requires rerouting all client traffic.
Highest integration cost — not feasible for the zero-integration positioning.

---

**Tier mapping to blocking approach:**

**Starter tier (monitoring only)**
Client grants S3 GetObject permission. Engine detects and records. No write access
to client infrastructure. Dashboard shows findings, no automated blocking.

**Growth / Pro tier (WAF rule injection enabled)**
Client additionally grants wafv2:UpdateIPSet + wafv2:GetIPSet on their WebACL,
OR provides a Cloudflare API token with Firewall Rules permission.
When engine produces a high-confidence verdict, push_blocks task:
- AWS: calls boto3 wafv2.update_ip_set to add IP to client's WAF IP set
- Cloudflare: calls Cloudflare API to create a block rule for the IP
Dashboard shows blocked vs detected split, with expiry and whitelist controls.

Blocking code is in the repo from day one but only activates for Growth/Pro clients.
The trust-first sequencing is intentional: monitoring is read-only and any CTO can
approve it in 5 minutes. Blocking touches production and requires 60–90 days of
proven low false-positive detection before a client will commit.

---

## Pricing Tiers

> ⚠️ Pricing needs final verification — INR figures are indicative, USD conversions
> to be confirmed before publishing.

| Tier | Price | Volume | Blocking | Notes |
|---|---|---|---|---|
| **Pilot (Early Adopter)** | ₹0 for 60 days, then ₹4,999/mo | — | No | First 5 clients; manual onboarding; weekly check-in call included |
| **Starter** | ₹9,999/mo (~$120) | Up to 10M API calls/mo | No | Detection + dashboard |
| **Growth** | ₹14,999/mo (~$180) | Up to 50M API calls/mo | Yes (WAF/CF) | + WAF rule injection, Slack alerts, priority support |
| **Pro** | ₹29,999/mo (~$360) | Up to 200M API calls/mo | Yes (WAF/CF) | + custom thresholds, quarterly business review |
| **Clew Audit** | $1,000 USD (one-time) | Full historical logs | No | Full historical log audit — scans entire log history, surfaces all past incidents, delivered as a report via the dashboard |

**Clew Audit** is a standalone one-time purchase. Client provides S3 read access to
their full historical logs. Clew runs a complete retrospective analysis and surfaces
every incident pattern found across the entire history. Useful as a sales entry point
("find out what's already happened") and as an upsell to an ongoing Starter/Growth plan.

Payment: first 5 clients are invoiced manually. No payment processor integration in v1.

---

## Key Decisions

- No inline proxy, no SDK, no client code changes ever.
- Monorepo: frontend and backend in same repo. One deploy target.
- No Vercel. Everything on one EC2 behind Nginx.
- No PDF reports. Everything surfaces through the dashboard.
- LTM persists in PostgreSQL (ip_memory table). Survives restarts.
- STM lives in Redis with TTL per processing window.
- PDF generation, Slack alerts, middleware SDK are future work. Not in v1.
- First 5 clients: invoice manually. No payment processor integration in v1.
- Blocking code is in the repo from day one but only activates for growth tier clients.

---

## Local Dev Setup

```bash
# Start postgres and redis
docker-compose up -d

# Python backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000

# Celery (separate terminal)
celery -A workers.celery_app worker --beat --loglevel=info

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Environment variables (see .env.example):
DATABASE_URL, REDIS_URL, SECRET_KEY (JWT), AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY, AWS_REGION, SES_FROM_EMAIL, CLOUDFLARE_API_TOKEN

---

## Deployment (EC2)

Single EC2 t3.small running Ubuntu 24.04.
RDS PostgreSQL t3.micro (separate, managed).
Redis self-hosted on the same EC2 to save cost until 15+ clients.

Process manager: PM2 runs Next.js, Uvicorn, and Celery as persistent processes.
Nginx handles SSL termination (Let's Encrypt via certbot) and routing.
DNS: Namecheap A records → EC2 Elastic IP.

Deploy flow: SSH → git pull → pip install → npm build → pm2 restart all.
No CI/CD in v1. Manual deploy is fine for first 10 clients.
