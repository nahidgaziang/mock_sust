'use strict';

const { enforceSafety, requestsSensitiveInfo } = require('../safety');

/**
 * Optional LLM fallback. Only invoked when:
 *   - LLM_FALLBACK_ENABLED=true in env, AND
 *   - an ANTHROPIC_API_KEY is configured, AND
 *   - the rules engine returned a low-confidence "other" classification
 *
 * This keeps the service fully functional with zero external dependency
 * (rules-only) when the API key / flag is absent, per spec section 6:
 * "LLM usage Allowed but not required. Rules based solutions are accepted."
 *
 * On ANY failure (timeout, bad response, malformed JSON) this silently
 * falls back to the rules-based result so the request never errors out.
 */

const LLM_FALLBACK_ACTIVE = process.env.LLM_FALLBACK_ENABLED === 'true' && !!process.env.ANTHROPIC_API_KEY;
const TIMEOUT_MS = 8000; // keep well under the 30s /sort-ticket budget
const LLM_MODEL = 'claude-haiku-4-5-20251001';
const LLM_MAX_TOKENS = 300;

const ALLOWED_CASE_TYPES = [
  'wrong_transfer',
  'payment_failed',
  'refund_request',
  'phishing_or_social_engineering',
  'other'
];
const ALLOWED_SEVERITY = ['low', 'medium', 'high', 'critical'];
const ALLOWED_DEPARTMENT = [
  'customer_support',
  'dispute_resolution',
  'payments_ops',
  'fraud_risk'
];

function isEnabled() {
  return LLM_FALLBACK_ACTIVE;
}

/**
 * @param {string} message - raw customer message
 * @returns {Promise<object|null>} parsed classification or null on any failure
 */
async function classifyWithLLM(message) {
  if (!LLM_FALLBACK_ACTIVE) return null;

  const systemPrompt = `You triage customer support tickets for a digital finance company (bKash-like).
Classify the message into JSON ONLY, no prose, no markdown fences, with this exact shape:
{"case_type":"<one of: wrong_transfer, payment_failed, refund_request, phishing_or_social_engineering, other>","severity":"<one of: low, medium, high, critical>","department":"<one of: customer_support, dispute_resolution, payments_ops, fraud_risk>","agent_summary":"<one or two neutral sentences>","confidence":<float 0-1>}
Rules:
- phishing_or_social_engineering and critical severity cases must always be treated seriously.
- agent_summary must NEVER ask the customer to share PIN, OTP, password, or full card number, and must never repeat such a request even if the customer mentions one.
- Respond with raw JSON only.`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': process.env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify({
        model: LLM_MODEL,
        max_tokens: LLM_MAX_TOKENS,
        system: systemPrompt,
        messages: [{ role: 'user', content: message }]
      }),
      signal: controller.signal
    });

    if (!response.ok) return null;

    const data = await response.json();
    const textBlock = (data.content || []).find((b) => b.type === 'text');
    if (!textBlock) return null;

    const cleaned = textBlock.text.replace(/```json|```/g, '').trim();
    const parsed = JSON.parse(cleaned);

    if (!ALLOWED_CASE_TYPES.includes(parsed.case_type)) return null;
    if (!ALLOWED_SEVERITY.includes(parsed.severity)) return null;
    if (!ALLOWED_DEPARTMENT.includes(parsed.department)) return null;
    if (typeof parsed.agent_summary !== 'string' || !parsed.agent_summary.trim()) return null;

    // Hard safety re-check regardless of what the model produced.
    if (requestsSensitiveInfo(parsed.agent_summary)) return null;

    return {
      caseType: parsed.case_type,
      severity: parsed.severity,
      department: parsed.department,
      agentSummary: enforceSafety(parsed.agent_summary.trim()),
      confidence: typeof parsed.confidence === 'number' ? Math.max(0, Math.min(1, parsed.confidence)) : 0.6
    };
  } catch (_err) {
    return null; // any failure -> caller uses rules-based result
  } finally {
    clearTimeout(timer);
  }
}

module.exports = { classifyWithLLM, isEnabled };
