'use strict';

require('dotenv').config();
const express = require('express');
const { classify } = require('./classifier/rules');
const { buildSummary } = require('./classifier/summary');
const { classifyWithLLM, isEnabled: llmEnabled } = require('./classifier/llmFallback');
const { enforceSafety } = require('./safety');

const app = express();
app.use(express.json({ limit: '64kb' }));

const PORT = process.env.PORT || 3000;

const VALID_CHANNELS = new Set(['app', 'sms', 'call_center', 'merchant_portal']);
const VALID_LOCALES = new Set(['bn', 'en', 'mixed']);

// ---------------------------------------------------------------------------
// GET /health
// ---------------------------------------------------------------------------
app.get('/health', (_req, res) => {
  res.status(200).json({
    status: 'ok',
    service: 'queuestorm-ticket-sorter',
    timestamp: new Date().toISOString(),
    llm_fallback_enabled: llmEnabled()
  });
});

// ---------------------------------------------------------------------------
// POST /sort-ticket
// ---------------------------------------------------------------------------
app.post('/sort-ticket', async (req, res) => {
  const body = req.body || {};
  const { ticket_id, channel, locale, message } = body;

  // --- Basic validation -----------------------------------------------
  if (typeof ticket_id !== 'string' || !ticket_id.trim()) {
    return res.status(400).json({ error: 'ticket_id is required and must be a non-empty string' });
  }
  if (typeof message !== 'string' || !message.trim()) {
    return res.status(400).json({ error: 'message is required and must be a non-empty string' });
  }
  if (channel !== undefined && !VALID_CHANNELS.has(channel)) {
    return res.status(400).json({ error: `channel must be one of: ${[...VALID_CHANNELS].join(', ')}` });
  }
  if (locale !== undefined && !VALID_LOCALES.has(locale)) {
    return res.status(400).json({ error: `locale must be one of: ${[...VALID_LOCALES].join(', ')}` });
  }

  // --- Rules-based classification (always runs; this is our baseline) -
  const ruleResult = classify(message);

  let caseType = ruleResult.caseType;
  let severity = ruleResult.severity;
  let department = ruleResult.department;
  let confidence = ruleResult.confidence;
  let agentSummary = buildSummary(caseType, ruleResult.signals.amount);

  // --- Optional LLM fallback, only for low-confidence "other" ----------
  if (ruleResult.signals.lowConfidence && llmEnabled()) {
    try {
      const llmResult = await classifyWithLLM(message);
      if (llmResult) {
        caseType = llmResult.caseType;
        severity = llmResult.severity;
        department = llmResult.department;
        confidence = llmResult.confidence;
        agentSummary = llmResult.agentSummary;
      }
    } catch (_err) {
      // Swallow — rules-based result already set above as a safe default.
    }
  }

  // --- Safety rule enforcement (final line of defense) -----------------
  agentSummary = enforceSafety(agentSummary);

  // Spec rule: human_review_required = true for critical severity OR phishing
  const humanReviewRequired = severity === 'critical' || caseType === 'phishing_or_social_engineering';

  return res.status(200).json({
    ticket_id,
    case_type: caseType,
    severity,
    department,
    agent_summary: agentSummary,
    human_review_required: humanReviewRequired,
    confidence: Math.round(confidence * 100) / 100
  });
});

// --- Fallback error handler ----------------------------------------------
app.use((err, _req, res, _next) => {
  // eslint-disable-next-line no-console
  console.error(err);
  res.status(500).json({ error: 'internal_server_error' });
});

app.listen(PORT, () => {
  // eslint-disable-next-line no-console
  console.log(`QueueStorm ticket sorter listening on port ${PORT}`);
});

module.exports = app;
