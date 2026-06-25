# QueueStorm Ticket Sorter

> **SUST CSE Carnival 2026 — Codex Community Hackathon**  
> QueueStorm Warmup · Mock Preliminary · CRM Ticket Triage Service

A stateless, production-ready REST API that reads a raw customer support ticket and returns a fully structured triage classification — case type, severity, owning department, a neutral agent summary, a human-review flag, and a confidence score.

Zero database. Zero GPU. Sub-100 ms median response time.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [API Reference](#api-reference)
  - [GET /health](#get-health)
  - [POST /sort-ticket](#post-sort-ticket)
  - [Error Responses](#error-responses)
- [Classification Logic](#classification-logic)
  - [Case Types & Departments](#case-types--departments)
  - [Severity Rules](#severity-rules)
  - [Safety Rule](#safety-rule)
  - [Optional LLM Fallback](#optional-llm-fallback)
- [Project Structure](#project-structure)
- [Running Locally](#running-locally)
- [Running Tests](#running-tests)
- [Environment Variables](#environment-variables)
- [Deployment](#deployment)
  - [Option A — Render (Recommended)](#option-a--render-recommended)
  - [Option B — Fly.io](#option-b--flyio)
  - [Option C — Docker (anywhere)](#option-c--docker-anywhere)
  - [Option D — Bare VM / PM2](#option-d--bare-vm--pm2)
  - [Post-Deploy Checklist](#post-deploy-checklist)
- [Known Limitations](#known-limitations)

---

## Overview

Customers contact bKash-style digital wallets with a wide variety of issues — money sent to the wrong number, failed transactions, phishing calls, refund requests, and app bugs. This service classifies each incoming ticket into a structured payload that lets support agents immediately understand what happened and where to route the case.

**Key design decisions:**

| Decision | Rationale |
|---|---|
| Rules-based by default | Zero external dependency, deterministic, sub-100 ms, no API key required |
| Phishing short-circuits all other rules | Safety-critical cases must never be diluted by other keyword overlaps |
| Safety filter on every summary | `agent_summary` can never ask a customer to share PIN / OTP / password / card number — by construction *and* by a last-line regex guard |
| Optional LLM fallback | Consults Claude only for low-confidence `other` tickets when an API key is configured |

---

## Architecture

```
HTTP request
     │
     ▼
┌─────────────────────────────────────────────────┐
│  server.js  (Express, input validation)         │
│                                                 │
│  ┌──────────────────────────────────────────┐   │
│  │  classifier/rules.js                     │   │
│  │  ─ Regex/keyword scorer per case type    │   │
│  │  ─ Phishing short-circuit                │   │
│  │  ─ Amount extraction for severity        │   │
│  └──────────────────────────────────────────┘   │
│           │ low-confidence "other"?              │
│           ▼  (LLM_FALLBACK_ENABLED=true only)   │
│  ┌──────────────────────────────────────────┐   │
│  │  classifier/llmFallback.js               │   │
│  │  ─ Calls Claude Haiku via Anthropic API  │   │
│  │  ─ Strict schema + enum validation       │   │
│  │  ─ 8 s timeout, silent failure fallback  │   │
│  └──────────────────────────────────────────┘   │
│           │                                      │
│           ▼                                      │
│  ┌──────────────────────────────────────────┐   │
│  │  classifier/summary.js                   │   │
│  │  ─ Template-based agent_summary          │   │
│  └──────────────────────────────────────────┘   │
│           │                                      │
│           ▼                                      │
│  ┌──────────────────────────────────────────┐   │
│  │  safety.js  (last-line filter)           │   │
│  │  ─ Rewrites any summary that matches     │   │
│  │    a sensitive-info-request pattern      │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
     │
     ▼
JSON response
```

---

## API Reference

### `GET /health`

Returns the service status. Must respond with HTTP 200 within 10 seconds.

**Response `200 OK`**
```json
{
  "status": "ok",
  "service": "queuestorm-ticket-sorter",
  "timestamp": "2026-06-25T16:00:00.000Z",
  "llm_fallback_enabled": false
}
```

---

### `POST /sort-ticket`

Classifies a customer support ticket.

**Request body** (`Content-Type: application/json`)

| Field | Type | Required | Allowed Values |
|---|---|---|---|
| `ticket_id` | string | ✅ | any non-empty string |
| `message` | string | ✅ | raw customer message, non-empty |
| `channel` | string | ❌ | `app`, `sms`, `call_center`, `merchant_portal` |
| `locale` | string | ❌ | `bn`, `en`, `mixed` |

```json
{
  "ticket_id": "T-001",
  "channel": "app",
  "locale": "en",
  "message": "I sent 5000 taka to the wrong number this morning, please help me get it back"
}
```

**Response `200 OK`**

| Field | Type | Description |
|---|---|---|
| `ticket_id` | string | Echoed from request |
| `case_type` | string | See [Case Types](#case-types--departments) |
| `severity` | string | `low` · `medium` · `high` · `critical` |
| `department` | string | See [Case Types](#case-types--departments) |
| `agent_summary` | string | 1–2 neutral sentences. **Never requests sensitive credentials.** |
| `human_review_required` | boolean | `true` when `severity === "critical"` OR `case_type === "phishing_or_social_engineering"` |
| `confidence` | number | Float `0.0–1.0` |

```json
{
  "ticket_id": "T-001",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Customer reports sending 5000 BDT to an incorrect recipient and requests recovery of the funds.",
  "human_review_required": false,
  "confidence": 0.85
}
```

---

### Error Responses

| Status | Condition |
|---|---|
| `400` | `ticket_id` or `message` missing / empty |
| `400` | `channel` or `locale` present but not in the allowed enum |
| `500` | Unexpected server error |

```json
{ "error": "message is required and must be a non-empty string" }
```

---

## Classification Logic

### Case Types & Departments

| `case_type` | `department` | Description |
|---|---|---|
| `phishing_or_social_engineering` | `fraud_risk` | OTP/PIN scam, fake bKash agent, suspicious link/call |
| `wrong_transfer` | `dispute_resolution` | Money sent to wrong recipient |
| `payment_failed` | `payments_ops` | Transaction failed but balance deducted |
| `refund_request` | `customer_support` (or `dispute_resolution` if contested) | Customer wants money back |
| `other` | `customer_support` | App crashes, login issues, general bugs |

### Severity Rules

**Phishing / social-engineering** — always `critical`.

**Wrong transfer:**
- `critical` — if urgency keywords present (`urgent`, `scam`, `fraud`, `hacked`, `stolen`)
- `medium` — if an amount < 500 BDT is explicitly stated
- `high` — all other cases (default, since money already left the account)

**Payment failed:**
- `high` — default (balance deducted = urgent to customer)
- `medium` — if amount < 500 BDT explicitly stated

**Refund request:**
- `medium` — if message contains dispute language (`dispute`, `wrong`, `never received`, `fraud`)
- `low` — standard refund / change of mind

**Other:**
- `low` always

### Safety Rule

The `agent_summary` field:
1. Is built from **fixed neutral templates** that never mention or request PIN / OTP / password / card numbers.
2. Additionally passes through a **regex filter** (`safety.js`) that replaces any summary matching a sensitive-info-request pattern with a safe generic fallback — regardless of whether the summary came from a template or the LLM fallback.

This means the safety guarantee holds even if the LLM produces unexpected output.

### Optional LLM Fallback

When `LLM_FALLBACK_ENABLED=true` and `ANTHROPIC_API_KEY` is set:

- Only triggered for tickets the rules engine couldn't classify confidently (low-confidence `other`)
- Calls **Claude Haiku** via the Anthropic Messages API with an 8-second timeout
- Response is strictly validated against all enum lists before being accepted
- `agent_summary` is safety-filtered again regardless of LLM output
- **Any failure** (timeout, network error, malformed JSON, schema mismatch) silently falls back to the rules-based result — the request never returns an error because of LLM issues

With LLM fallback off (the default), the service has **zero external dependencies**.

---

## Project Structure

```
d:\HAC_SUST\
├── src/
│   ├── server.js                   Express app, routing, validation, logger
│   ├── safety.js                   PIN/OTP/password/CVV guard (last-line filter)
│   └── classifier/
│       ├── rules.js                Core rules-based classifier & severity logic
│       ├── summary.js              Template-based agent_summary generator
│       └── llmFallback.js          Optional Claude fallback for low-confidence "other"
├── test/
│   └── sample-cases.test.js        5 public sample cases + safety + validation checks
├── .env.example                    Environment variable reference
├── .gitignore                      Excludes node_modules/ and .env
├── Dockerfile                      Production Docker image (node:18-alpine)
├── fly.toml                        Fly.io deployment config (Singapore region)
├── render.yaml                     Render one-click deploy config
└── package.json
```

---

## Running Locally

**Requirements:** Node.js 18+

```bash
git clone https://github.com/nahidgaziang/mock_sust.git
cd mock_sust
npm install
cp .env.example .env        # edit only if enabling the LLM fallback
npm start                   # listens on PORT (default 3000)
```

Verify:
```bash
# Health check
curl http://localhost:3000/health

# Sample ticket — wrong transfer
curl -X POST http://localhost:3000/sort-ticket \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"T-001","channel":"app","locale":"en","message":"I sent 3000 taka to wrong number"}'

# Sample ticket — phishing
curl -X POST http://localhost:3000/sort-ticket \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"T-002","message":"Someone called asking my OTP, is that bKash?"}'
```

---

## Running Tests

```bash
npm test
```

The test runner (`test/sample-cases.test.js`) starts the Express app in-process on port `3999` and runs:

1. `GET /health` — checks `status: "ok"`
2. All **5 public sample cases** from the spec — verifies `case_type`, `severity`, `confidence` type, `human_review_required` type and value, and that `agent_summary` never requests sensitive credentials
3. A **400 validation check** — missing `message` field

Expected output (all passing):
```
PASS  GET /health
PASS  "I sent 3000 to wrong number" -> wrong_transfer/high
PASS  "Payment failed but balance deducted" -> payment_failed/high
PASS  "Someone called asking my OTP, is that bKash?" -> phishing_or_social_engineering/critical
PASS  "Please refund my last transaction, I changed my mind" -> refund_request/low
PASS  "App crashed when I opened it" -> other/low
PASS  missing message field -> 400

7 passed, 0 failed
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `3000` | Port the HTTP server listens on. Most PaaS providers inject this automatically. |
| `NODE_ENV` | — | Set to `production` in deployed environments. |
| `LLM_FALLBACK_ENABLED` | `false` | Set to `true` to enable the Claude fallback for low-confidence tickets. Requires `ANTHROPIC_API_KEY`. |
| `ANTHROPIC_API_KEY` | — | Your Anthropic API key. **Never commit to source control.** Set as a secret in your platform's environment settings. |

> **Security note:** Copy `.env.example` to `.env` for local development. The `.env` file is gitignored. On all deployed platforms, set secrets via the platform's environment variable settings — never commit them to the repository.

---

## Deployment

The service is a **stateless** Node/Express HTTP server with no database and no GPU requirement. It deploys identically on any cloud platform.

### Option A — Render (Recommended)

`render.yaml` is pre-configured for one-click deploy on the free tier, Singapore region.

1. Push this repo to GitHub.
2. Go to [render.com](https://render.com) → **New +** → **Web Service** → connect the repo.
3. Render auto-detects `render.yaml`. Confirm settings and click **Create Web Service**.
4. Wait ~2 minutes for the first build to complete.
5. Your live HTTPS URL: `https://queuestorm-ticket-sorter.onrender.com`

> **Note:** Render's free tier spins down after 15 minutes of inactivity. The first request after sleep may take up to 30 s (within the spec's budget). Warm it up before submission time.

### Option B — Fly.io

`fly.toml` is pre-configured (Singapore region, shared 256 MB VM).

```bash
# One-time setup
winget install Fly-io.flyctl
fly auth login

# Deploy
fly deploy --app queuestorm-ticket-sorter

# Get your live URL
fly status
```

Live URL: `https://queuestorm-ticket-sorter.fly.dev`

Fly.io machines auto-stop when idle and auto-start on the first request, with sub-second cold-start.

### Option C — Docker (anywhere)

```bash
docker build -t queuestorm-ticket-sorter .

docker run -p 3000:3000 \
  -e PORT=3000 \
  -e NODE_ENV=production \
  -e LLM_FALLBACK_ENABLED=false \
  queuestorm-ticket-sorter
```

Works on Render (Docker runtime), Railway, EC2, GCP Cloud Run, Poridhi Lab, or any container host.

### Option D — Bare VM / PM2

```bash
git clone https://github.com/nahidgaziang/mock_sust.git
cd mock_sust
npm install --omit=dev
npm install -g pm2
pm2 start src/server.js --name queuestorm -- --port 3000
pm2 save && pm2 startup
```

Put **Nginx** or the platform's load balancer in front to terminate HTTPS and reverse-proxy to port 3000 (the spec requires a public HTTPS endpoint).

---

### Post-Deploy Checklist

- [ ] `GET https://<your-domain>/health` returns `200` within 10 s
- [ ] `POST https://<your-domain>/sort-ticket` returns valid JSON within 30 s
- [ ] No secrets committed to the repo (`.env` is gitignored)
- [ ] `ANTHROPIC_API_KEY` set as a **platform secret**, not in source, if LLM fallback is enabled
- [ ] Submit the live HTTPS URL to the Google Form

---

## Known Limitations

- **Paraphrased phrasing** — keyword/regex matching can miss heavily reworded messages that don't match any detector. Mitigated (optionally) by the LLM fallback for low-confidence `other` cases.
- **Bangla script** — support is currently Banglish/transliterated keyword matching, not native Unicode Bangla NLP.
- **Render cold starts** — the free tier has ~15 s cold-start after inactivity. Plan accordingly before the grader hits the endpoint.
