# QueueStorm Ticket Sorter

CRM ticket triage service for the SUST CSE Carnival 2026 — Codex Community
Hackathon, QueueStorm Warmup (Mock Preliminary).

Reads one customer support ticket and returns a structured classification:
case type, severity, owning department, a neutral one/two-sentence agent
summary, a `human_review_required` flag, and a confidence score.

## How it classifies tickets

Classification is **rules-based by default** (regex/keyword detectors,
zero external dependencies, zero GPU, sub-second response time) and
satisfies the spec's "Rules based solutions are accepted" allowance.

An **optional LLM fallback** (Claude Haiku via the Anthropic API) can be
turned on to give a second opinion specifically on low-confidence "other"
classifications — tickets the rules engine couldn't confidently bucket.
It is off unless you explicitly enable it; the service is fully
functional without it.

Detection order:
1. **Phishing/social-engineering patterns are checked first** and always
   take priority (OTP/PIN/password/CVV requests, fake-agent claims,
   suspicious links) — these are the safety-critical cases.
2. Remaining categories (`wrong_transfer`, `payment_failed`,
   `refund_request`, `other`) are scored by keyword/regex matches in
   English and common Bangla/Banglish phrasing, and the highest-scoring
   category wins.
3. If nothing matches confidently, the ticket is marked `other` with low
   confidence — and, if enabled, handed to the LLM fallback.

Severity and department are then derived from the case type, any taka
amount mentioned, and urgency hints (e.g. "urgent", "scam", "fraud").

`human_review_required` is `true` whenever severity is `critical` or the
case type is `phishing_or_social_engineering`, per the spec.

### Safety rule enforcement

The `agent_summary` field is built from fixed, neutral templates that
never reference or request PIN/OTP/password/card numbers by
construction. As a last line of defense (also covering LLM-fallback
output), every summary passes through a filter that rewrites it to a
safe generic sentence if it ever matches a "please share your OTP/PIN/
password/card number" pattern.

## API

### `GET /health`
Returns `200` with service status. Responds in well under the 10s budget.

### `POST /sort-ticket`
Request:
```json
{
  "ticket_id": "T-001",
  "channel": "app",
  "locale": "en",
  "message": "I sent 5000 taka to a wrong number this morning, please help me get it back"
}
```

Response:
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

`channel` and `locale` are optional but validated against the allowed
enums if present. Missing/invalid `ticket_id` or `message` returns `400`.

## Project structure
```
src/
  server.js                 Express app, routes, validation
  safety.js                 PIN/OTP/password/card-number guard
  classifier/
    rules.js                Core rules-based classifier
    summary.js              Template-based agent_summary generator
    llmFallback.js          Optional Claude API fallback for low-confidence "other"
test/
  sample-cases.test.js      Runs the 5 public sample cases + safety checks
Dockerfile
.env.example
```

## Running locally

Requirements: Node.js 18+.

```bash
git clone <this-repo-url>
cd queuestorm-ticket-sorter
npm install
cp .env.example .env       # edit if you want the LLM fallback
npm start                  # listens on PORT (default 3000)
```

Verify:
```bash
curl http://localhost:3000/health
curl -X POST http://localhost:3000/sort-ticket \
  -H 'Content-Type: application/json' \
  -d '{"ticket_id":"T-001","message":"I sent 3000 to wrong number"}'
```

Run the test suite (hits the 5 public sample cases + validation/safety checks):
```bash
npm test
```

### Enabling the optional LLM fallback
```bash
# in .env
LLM_FALLBACK_ENABLED=true
ANTHROPIC_API_KEY=sk-ant-...
```
With this off (default), the service has no external dependency at all.

## Deployment runbook

The service is a stateless Node/Express HTTP server with no database and
no GPU requirement, so it deploys identically on any of the platforms
below. Pick whichever was used for the live submission URL.

### Option A — Docker (works anywhere: Fly, Render, Railway, EC2, Poridhi Lab)
```bash
docker build -t queuestorm-ticket-sorter .
docker run -p 3000:3000 \
  -e PORT=3000 \
  -e LLM_FALLBACK_ENABLED=false \
  queuestorm-ticket-sorter
```

### Option B — Render (Web Service, no Docker)
1. Push this repo to GitHub.
2. Render dashboard → New → Web Service → connect the repo.
3. Build command: `npm install`
4. Start command: `npm start`
5. Add environment variables from `.env.example` if using the LLM fallback
   (`LLM_FALLBACK_ENABLED`, `ANTHROPIC_API_KEY`). Render injects `PORT`
   automatically — do not hardcode it.
6. Deploy. Render gives you an HTTPS URL automatically; confirm
   `https://<your-app>.onrender.com/health` returns `200`.

### Option C — Railway
1. Push this repo to GitHub.
2. Railway dashboard → New Project → Deploy from GitHub repo.
3. Railway auto-detects Node.js and runs `npm install && npm start`.
4. Set the same optional env vars under the "Variables" tab if needed.
5. Railway provisions a public HTTPS domain under Settings → Networking →
   "Generate Domain". Confirm `/health` responds.

### Option D — Fly.io
```bash
fly launch --no-deploy        # generates fly.toml, accept Node detection
fly secrets set LLM_FALLBACK_ENABLED=false   # and ANTHROPIC_API_KEY if used
fly deploy
fly status                    # gives you the https://<app>.fly.dev URL
```

### Option E — Bare VM / EC2 / Poridhi Lab
```bash
git clone <this-repo-url>
cd queuestorm-ticket-sorter
npm install
npm install -g pm2
pm2 start src/server.js --name queuestorm -- --port 3000
pm2 save
```
Put Nginx (or the platform's load balancer) in front to terminate HTTPS
and reverse-proxy to port 3000, since the spec requires the public
endpoint to be HTTPS.

### Post-deploy checklist
- [ ] `GET https://<your-domain>/health` returns `200` within 10s
- [ ] `POST https://<your-domain>/sort-ticket` returns valid JSON within 30s
- [ ] No secrets committed to the repo (`.env` is gitignored; use the
      platform's environment-variable settings instead)
- [ ] If LLM fallback is enabled, `ANTHROPIC_API_KEY` is set as a secret,
      not committed to source

## Known limitations
- Keyword/regex-based classification can miss heavily paraphrased or
  novel phrasing that doesn't match any of the patterns in
  `src/classifier/rules.js`; this is mitigated (optionally) by the LLM
  fallback for low-confidence `other` cases.
- Bangla support is currently Banglish/transliterated keyword matching,
  not native Bangla-script NLP.
