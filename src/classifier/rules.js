'use strict';

/**
 * Rule-based ticket classifier.
 *
 * Strategy: run a series of weighted keyword/regex detectors per case_type
 * (English + common Bangla/Banglish terms), score each category, and pick
 * the highest scoring one. Phishing/social-engineering detectors run FIRST
 * and short-circuit everything else, because those tickets are the most
 * safety-critical (OTP/PIN scams) and must never be misclassified as
 * "other" or "payment_failed".
 */

// ---------------------------------------------------------------------------
// Keyword banks (lowercase). Bangla terms are transliterated/Banglish since
// messages may arrive in bn, en, or mixed locale.
// ---------------------------------------------------------------------------

const PHISHING_PATTERNS = [
  /\botp\b/i,
  /\bpin\b/i,
  /\bcvv\b/i,
  /password/i,
  /\bpasswo?rd\b/i,
  /full card number/i,
  /card number/i,
  /(asked|asking|share|told me to give|chay\s*chilo|dite bolse).{0,30}(otp|pin|password|cvv)/i,
  /(otp|pin|password|cvv).{0,30}(asked|asking|share|dite bolse|chay)/i,
  /claims? to be (from )?bkash/i,
  /is (that|this) (really|actually )?bkash/i,
  /someone called/i,
  /fake (call|agent|executive|representative)/i,
  /lottery|prize|won.{0,15}(taka|bdt|money)/i,
  /bkash (agent|officer|executive) (called|called me|phone korse)/i,
  /amake otp dite bolse/i,
  /verify.{0,20}account.{0,20}(call|sms|link)/i,
  /click.{0,15}(this )?link/i,
  /suspicious (call|sms|message|link)/i,
  /impersonat/i
];

const WRONG_TRANSFER_PATTERNS = [
  /wrong number/i,
  /wrong (recipient|account|person)/i,
  /sent.{0,20}wrong/i,
  /vul (number|account)/i,
  /accidentally sent/i,
  /mistakenly (sent|transferred)/i,
  /sent (it |money )?to (the )?wrong/i,
  /taka.{0,15}wrong/i,
  /get (it |my money )?back/i,
  /recover my money/i,
  /sent money to (a |the )?stranger/i
];

const PAYMENT_FAILED_PATTERNS = [
  /payment failed/i,
  /transaction failed/i,
  /failed but (the )?balance/i,
  /balance (was |got )?deducted/i,
  /money (was )?deducted/i,
  /deducted but/i,
  /transaction (was )?unsuccessful/i,
  /payment (didn'?t|did not) (go through|complete)/i,
  /taka cut hoye gese/i,
  /balance kete nise/i,
  /failed.{0,15}deduct/i,
  /double (charged|deduction|deducted)/i,
  /charged twice/i
];

const REFUND_PATTERNS = [
  /refund/i,
  /changed my mind/i,
  /want.{0,10}money back/i,
  /return my (money|payment)/i,
  /cancel.{0,15}(order|transaction|payment)/i,
  /taka ferot/i,
  /ferot dao/i
];

const OTHER_HINTS = [
  /crash(ed)?/i,
  /app (not working|isn'?t working|hangs|freezes|freeze)/i,
  /login (issue|problem)/i,
  /can'?t (log ?in|open the app|access)/i,
  /error message/i,
  /slow|loading forever|not loading/i,
  /update (issue|problem)/i,
  /bug/i
];

const CRITICAL_HINTS = [/urgent/i, /immediately/i, /scam/i, /fraud/i, /hacked/i, /stole|stolen/i];
const HIGH_AMOUNT_PATTERN = /(\d{1,3}(,\d{3})*|\d+)\s*(taka|bdt|tk)\b/i;

function countMatches(text, patterns) {
  let score = 0;
  for (const p of patterns) {
    if (p.test(text)) score += 1;
  }
  return score;
}

function extractAmount(text) {
  const m = text.match(/(\d{1,3}(?:,\d{3})*|\d+)\s*(?:taka|bdt|tk)\b/i);
  if (!m) return null;
  const num = parseInt(m[1].replace(/,/g, ''), 10);
  return Number.isFinite(num) ? num : null;
}

/**
 * @param {string} message
 * @returns {{caseType: string, severity: string, department: string, confidence: number, signals: object}}
 */
function classify(message) {
  const text = (message || '').toLowerCase();

  const scores = {
    phishing_or_social_engineering: countMatches(text, PHISHING_PATTERNS),
    wrong_transfer: countMatches(text, WRONG_TRANSFER_PATTERNS),
    payment_failed: countMatches(text, PAYMENT_FAILED_PATTERNS),
    refund_request: countMatches(text, REFUND_PATTERNS),
    other: countMatches(text, OTHER_HINTS)
  };

  // Phishing short-circuits: any phishing signal at all takes priority,
  // since these are safety-critical and must not be diluted by other
  // keyword overlaps (e.g. a phishing message that also mentions "taka").
  if (scores.phishing_or_social_engineering > 0) {
    return finalize('phishing_or_social_engineering', text, scores);
  }

  // Pick the highest-scoring non-phishing category.
  const candidates = ['wrong_transfer', 'payment_failed', 'refund_request', 'other'];
  let best = 'other';
  let bestScore = 0;
  for (const c of candidates) {
    if (scores[c] > bestScore) {
      best = c;
      bestScore = scores[c];
    }
  }

  if (bestScore === 0) {
    // No rule fired confidently. Flag low-confidence "other" so the LLM
    // fallback (if enabled) can be consulted upstream.
    return finalize('other', text, scores, true);
  }

  return finalize(best, text, scores);
}

function finalize(caseType, text, scores, lowConfidence = false) {
  const amount = extractAmount(text);
  const hasCriticalHint = countMatches(text, CRITICAL_HINTS) > 0;

  let severity = 'low';
  let department = 'customer_support';
  let confidence = lowConfidence ? 0.35 : 0.6;

  switch (caseType) {
    case 'phishing_or_social_engineering':
      severity = 'critical';
      department = 'fraud_risk';
      confidence = 0.9;
      break;

    case 'wrong_transfer':
      department = 'dispute_resolution';
      // Wrong transfers mean money already left the customer's account to
      // the wrong person, which is inherently high-severity regardless of
      // whether a currency unit was mentioned. Only downgrade when a small
      // amount is explicitly stated.
      severity = amount && amount < 500 ? 'medium' : 'high';
      if (hasCriticalHint) severity = 'critical';
      confidence = 0.85;
      break;

    case 'payment_failed':
      department = 'payments_ops';
      severity = 'high'; // balance deducted = always urgent for the customer
      if (amount && amount < 500) severity = 'medium';
      confidence = 0.8;
      break;

    case 'refund_request': {
      // Contested/large refunds escalate to dispute resolution per spec table.
      const contested = /dispute|wrong|not satisfied|never received|didn'?t receive|fraud/i.test(text);
      department = contested ? 'dispute_resolution' : 'customer_support';
      severity = contested ? 'medium' : 'low';
      confidence = 0.75;
      break;
    }

    case 'other':
    default:
      department = 'customer_support';
      severity = 'low';
      confidence = lowConfidence ? 0.35 : 0.55;
      break;
  }

  return {
    caseType,
    severity,
    department,
    confidence,
    signals: { scores, amount, hasCriticalHint, lowConfidence }
  };
}

module.exports = { classify, extractAmount };
