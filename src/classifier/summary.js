'use strict';

const { enforceSafety } = require('../safety');

/**
 * Produces a neutral, two-second-read agent summary based on the
 * classification result and the extracted amount (if any). Templates are
 * deliberately generic and never reference or request OTP/PIN/password/
 * card numbers, satisfying the safety rule by construction.
 */
function buildSummary(caseType, amount) {
  const amt = amount ? `${amount} BDT` : 'an unspecified amount';

  const templates = {
    wrong_transfer: `Customer reports sending ${amt} to an incorrect recipient and requests recovery of the funds.`,
    payment_failed: `Customer reports a failed transaction where the balance may have been deducted${amount ? ` (${amt})` : ''}.`,
    refund_request: `Customer is requesting a refund for a recent transaction${amount ? ` of ${amt}` : ''}.`,
    phishing_or_social_engineering: 'Customer reports a suspicious call or message requesting sensitive account details, indicating a possible phishing attempt.',
    other: 'Customer reported a general issue that does not fit standard categories and requires triage.'
  };

  const text = templates[caseType] || templates.other;
  return enforceSafety(text);
}

module.exports = { buildSummary };
