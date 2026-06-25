'use strict';

/**
 * Lightweight test runner (no external test framework) that:
 *  1. Starts the Express app in-process
 *  2. Hits /health
 *  3. Hits /sort-ticket with the 5 public sample cases from the spec
 *  4. Verifies case_type + severity match expected values
 *  5. Verifies the safety rule (no PIN/OTP/password/card requests in summary)
 *
 * Run with: npm test
 */

const http = require('http');

process.env.PORT = process.env.PORT || '3999';
const app = require('../src/server');

const PORT = process.env.PORT;
const BASE = `http://localhost:${PORT}`;

const SAMPLE_CASES = [
  { message: 'I sent 3000 to wrong number', expected_case_type: 'wrong_transfer', expected_severity: 'high' },
  { message: 'Payment failed but balance deducted', expected_case_type: 'payment_failed', expected_severity: 'high' },
  { message: 'Someone called asking my OTP, is that bKash?', expected_case_type: 'phishing_or_social_engineering', expected_severity: 'critical' },
  { message: 'Please refund my last transaction, I changed my mind', expected_case_type: 'refund_request', expected_severity: 'low' },
  { message: 'App crashed when I opened it', expected_case_type: 'other', expected_severity: 'low' }
];

function postJSON(path, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = http.request(
      `${BASE}${path}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) }
      },
      (res) => {
        let raw = '';
        res.on('data', (chunk) => (raw += chunk));
        res.on('end', () => {
          try {
            resolve({ status: res.statusCode, body: JSON.parse(raw) });
          } catch (e) {
            reject(e);
          }
        });
      }
    );
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

function getJSON(path) {
  return new Promise((resolve, reject) => {
    http
      .get(`${BASE}${path}`, (res) => {
        let raw = '';
        res.on('data', (chunk) => (raw += chunk));
        res.on('end', () => {
          try {
            resolve({ status: res.statusCode, body: JSON.parse(raw) });
          } catch (e) {
            reject(e);
          }
        });
      })
      .on('error', reject);
  });
}

const SENSITIVE_REQUEST_REGEX = /(share|provide|send|give|tell us|tell me|enter|confirm)\s+(your\s+)?(otp|pin|password|cvv|card number)/i;

async function run() {
  let passed = 0;
  let failed = 0;

  // Give the server a moment to bind
  await new Promise((r) => setTimeout(r, 300));

  // --- /health ---
  const health = await getJSON('/health');
  if (health.status === 200 && health.body.status === 'ok') {
    console.log('PASS  GET /health');
    passed++;
  } else {
    console.log('FAIL  GET /health', JSON.stringify(health.body));
    failed++;
  }

  // --- sample cases ---
  for (let i = 0; i < SAMPLE_CASES.length; i++) {
    const c = SAMPLE_CASES[i];
    const ticketId = `T-${String(i + 1).padStart(3, '0')}`;
    const resp = await postJSON('/sort-ticket', {
      ticket_id: ticketId,
      channel: 'app',
      locale: 'en',
      message: c.message
    });

    const b = resp.body;
    const checks = [];

    if (resp.status !== 200) checks.push(`status ${resp.status} != 200`);
    if (b.ticket_id !== ticketId) checks.push(`ticket_id mismatch: ${b.ticket_id}`);
    if (b.case_type !== c.expected_case_type) checks.push(`case_type ${b.case_type} != ${c.expected_case_type}`);
    if (b.severity !== c.expected_severity) checks.push(`severity ${b.severity} != ${c.expected_severity}`);
    if (typeof b.confidence !== 'number' || b.confidence < 0 || b.confidence > 1) checks.push(`bad confidence ${b.confidence}`);
    if (typeof b.human_review_required !== 'boolean') checks.push('human_review_required not boolean');
    if (SENSITIVE_REQUEST_REGEX.test(b.agent_summary || '')) checks.push('SAFETY VIOLATION: summary requests sensitive info');

    // Safety rule cross-check: critical/phishing must always require human review
    if ((b.severity === 'critical' || b.case_type === 'phishing_or_social_engineering') && b.human_review_required !== true) {
      checks.push('human_review_required should be true for critical/phishing');
    }

    if (checks.length === 0) {
      console.log(`PASS  "${c.message}" -> ${b.case_type}/${b.severity}`);
      passed++;
    } else {
      console.log(`FAIL  "${c.message}" ->`, checks.join('; '), JSON.stringify(b));
      failed++;
    }
  }

  // --- validation: missing required field ---
  const badResp = await postJSON('/sort-ticket', { ticket_id: 'T-999' });
  if (badResp.status === 400) {
    console.log('PASS  missing message field -> 400');
    passed++;
  } else {
    console.log('FAIL  missing message field should 400, got', badResp.status);
    failed++;
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
