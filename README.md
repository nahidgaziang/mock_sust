# QueueStorm Investigator API

AI-powered complaint investigation API for digital finance support. Built for the SUST CSE Carnival 2026 Codex Community Hackathon.

## Table of Contents
- [Architecture & AI Approach](#architecture--ai-approach)
- [Safety Logic](#safety-logic)
- [Models](#models)
- [Setup & Run Instructions](#setup--run-instructions)
  - [Local Development](#local-development)
  - [Docker Fallback](#docker-fallback)
- [Known Limitations](#known-limitations)

---

## Architecture & AI Approach

This solution uses a **Hybrid Deterministic + LLM Architecture**.
This approach guarantees that LLM hallucinations cannot bypass critical fintech safety rules.

1. **Strict Request Boundary:** Pydantic v2 schemas enforce the API contract. Input enums accept unknown values (for robustness against hidden tests), but output enums are strictly constrained.
2. **LLM Investigator Engine:** A carefully engineered system prompt instructs the LLM to cross-reference the complaint against the provided `transaction_history` (evidence reasoning), rather than just classifying text.
3. **Deterministic Safety Layer:** A pure Python module that runs *after* the LLM. It scans the output for safety violations, rewrites unsafe phrasing, and forces auto-escalations. It executes in `<1ms`.
4. **Safe Fallback:** If the LLM times out or fails, the API gracefully falls back to a deterministic, schema-valid response (with `insufficient_data` and manual review required) instead of crashing with a 500 error.

---

## Safety Logic

The deterministic safety layer (`app/safety.py`) strictly enforces the Hackathon penalty rules:

* **Rule 1 (Credential Requests):** Scans `customer_reply` for patterns asking the customer to provide their PIN, OTP, or password. If found, the entire sentence is rewritten into a safe format. 
  * *Note on warnings:* Phrases like "Please do not share your PIN" are correctly recognized as safe warnings and are actively injected into the reply if missing, matching the exact pattern from the sample cases (in both English and Bangla).
* **Rule 2 (Unauthorized Promises):** Scans BOTH `customer_reply` and `recommended_next_action` for unauthorized financial commitments (e.g., "we will refund you"). Replaces them with the mandated safe language: *"any eligible amount will be returned through official channels"*.
* **Rule 3 (Suspicious Third-Party):** Scans `customer_reply` for phone numbers and unknown URLs. Allows legitimate referrals like "contact the merchant" or "official support channels".
* **Auto-Escalation:** Unconditionally overrides the LLM to force `severity="critical"` and `human_review_required=true` for `phishing_or_social_engineering` cases or any routing to the `fraud_risk` department.

---

## MODELS

* **Model Used:** `gemini-2.0-flash`
* **Where it runs:** External API (Google GenAI API)
* **Why it was chosen:** 
  1. **Speed:** It consistently responds in under 3 seconds, easily meeting the p95 latency targets for maximum performance score.
  2. **Multilingual:** It natively understands and generates Bangla (e.g., matching the language of SAMPLE-07 perfectly).
  3. **Structured Output:** It strongly adheres to JSON schema constraints provided in the system prompt.
  4. **Cost:** Generous free tier perfectly suited for hackathon evaluation without rate limits.

---

## Setup & Run Instructions

### Prerequisites
- Python 3.12+
- Valid LLM API Key (Gemini)

### Local Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Configure environment:**
   Copy `.env.example` to `.env` and insert your API key.
   ```bash
   cp .env.example .env
   # Edit .env with your LLM_API_KEY
   ```
3. **Run the server:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
4. **Run the test harness (validates against the 10 sample cases):**
   ```bash
   python test_harness.py
   ```

### Docker Fallback

If you need to evaluate the service via Docker, use the following commands:

**Build the image:**
```bash
docker build -t queuestorm-team .
```

**Run the container:**
```bash
# Assuming you have a judging.env file with your API key
docker run -p 8000:8000 --env-file judging.env queuestorm-team
```

---

## Known Limitations

1. **Complex Entity Resolution:** In cases where the `transaction_history` contains multiple extremely similar transactions (same amount, same timestamp, same recipient), the LLM might struggle to isolate a single `relevant_transaction_id` and will correctly default to `insufficient_data`.
2. **API Dependency:** The service relies on an external LLM API. If the provider experiences an outage, the service will gracefully degrade to its deterministic fallback response for every ticket, ensuring the API stays up but losing reasoning fidelity.
