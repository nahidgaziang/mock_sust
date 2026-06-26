"""
Deterministic safety guardrails for QueueStorm Investigator.

This module runs AFTER the LLM output and BEFORE the response is sent.
It is pure Python with no LLM calls — it executes in < 1ms.
It is the un-bypassable last line of defense against safety violations.

Safety Rules (from Problem Statement Section 8):
  Rule 1: Never ASK for PIN, OTP, password, or full card number. (-15 pts)
  Rule 2: Never confirm refund, reversal, account unblock without authority. (-10 pts)
  Rule 3: Never instruct customer to contact suspicious third party. (-10 pts)
  Auto-Escalation: phishing_or_social_engineering → critical + fraud_risk + human_review
"""

from __future__ import annotations

import re
from typing import Any, Dict

from app.schemas import CASE_TYPES, DEPARTMENTS, EVIDENCE_VERDICTS, SEVERITIES


# ---------------------------------------------------------------------------
# Rule 1: Credential Request Detection
# These patterns detect ASKING/REQUESTING the customer to provide credentials.
# WARNING phrases ("do not share your PIN") are SAFE and must NOT be flagged.
# ---------------------------------------------------------------------------

# Patterns that indicate ASKING for credentials (VIOLATIONS)
_CREDENTIAL_REQUEST_PATTERNS = [
    # "provide your PIN/OTP/password/card number"
    re.compile(r"\bprovide\s+(us\s+)?(your\s+)?(pin|otp|password|card\s*number)", re.IGNORECASE),
    # "enter your PIN/OTP/password"
    re.compile(r"\benter\s+(your\s+)?(pin|otp|password)", re.IGNORECASE),
    # "send us your OTP/PIN"
    re.compile(r"\bsend\s+(us\s+|me\s+)?(your\s+)?(otp|pin|password)", re.IGNORECASE),
    # "give us your PIN/OTP/password/card"
    re.compile(r"\bgive\s+(us\s+|me\s+)?(your\s+)?(pin|otp|password|card)", re.IGNORECASE),
    # "confirm with your OTP/PIN/password"
    re.compile(r"\bconfirm\s+(with\s+)?(your\s+)?(otp|pin|password)", re.IGNORECASE),
    # "verify using your PIN/OTP/password"
    re.compile(r"\bverify\s+(using\s+|with\s+)?(your\s+)?(pin|otp|password)", re.IGNORECASE),
    # "what is your PIN/OTP/password/card number"
    re.compile(r"\bwhat\s+is\s+your\s+(pin|otp|password|card\s*number)", re.IGNORECASE),
    # "tell us your PIN/OTP"
    re.compile(r"\btell\s+(us\s+|me\s+)?(your\s+)?(pin|otp|password)", re.IGNORECASE),
    # "need your PIN/OTP/password to"
    re.compile(r"\bneed\s+your\s+(pin|otp|password)\s+to\b", re.IGNORECASE),
    # "share your PIN/OTP" in a requesting context (NOT preceded by "do not" or "never")
    re.compile(r"(?<!\bdo not\s)(?<!\bdon't\s)(?<!\bnot\s)(?<!\bnever\s)\bshare\s+your\s+(pin|otp|password|card\s*number)", re.IGNORECASE),
]

# Safe phrases that must NOT be flagged (warnings to the customer)
_CREDENTIAL_SAFE_PATTERNS = [
    re.compile(r"\bdo\s+not\s+share\s+(your\s+)?(pin|otp|password)", re.IGNORECASE),
    re.compile(r"\bdon'?t\s+share\s+(your\s+)?(pin|otp|password)", re.IGNORECASE),
    re.compile(r"\bnever\s+(ask|share|request)\b.*\b(pin|otp|password)", re.IGNORECASE),
    re.compile(r"\bwe\s+never\s+ask\s+for\b.*\b(pin|otp|password)", re.IGNORECASE),
    # Bangla safe patterns
    re.compile(r"শেয়ার\s+করবেন\s+না", re.IGNORECASE),
    re.compile(r"পিন\s*(বা|ও|or)\s*ওটিপি", re.IGNORECASE),
]


def _has_credential_request(text: str) -> bool:
    """Check if text ASKS for credentials (not just warns about them)."""
    # First check if there are any safe warning phrases
    # If the only credential mentions are in safe contexts, return False
    for pattern in _CREDENTIAL_REQUEST_PATTERNS:
        match = pattern.search(text)
        if match:
            # Check if this match is inside a safe phrase context
            match_start = max(0, match.start() - 30)
            context_before = text[match_start:match.start()].lower()
            if any(safe in context_before for safe in [
                "do not", "don't", "dont", "never", "not to", "please do not",
                "should not", "shouldn't", "must not", "করবেন না"
            ]):
                continue  # This is a safe warning, skip
            return True
    return False


# ---------------------------------------------------------------------------
# Rule 2: Unauthorized Financial Promise Detection
# Checked on BOTH customer_reply AND recommended_next_action.
# ---------------------------------------------------------------------------

_UNAUTHORIZED_PROMISE_PATTERNS = [
    re.compile(r"\bwe\s+will\s+refund\b", re.IGNORECASE),
    re.compile(r"\bwe'?ll\s+refund\b", re.IGNORECASE),
    re.compile(r"\bwe\s+are\s+refunding\b", re.IGNORECASE),
    re.compile(r"\bwe\s+have\s+refunded\b", re.IGNORECASE),
    re.compile(r"\bwe\s+have\s+initiated\s+a\s+refund\b", re.IGNORECASE),
    re.compile(r"\brefund\s+has\s+been\s+processed\b", re.IGNORECASE),
    re.compile(r"\brefund\s+is\s+being\s+processed\b", re.IGNORECASE),
    re.compile(r"\byour\s+refund\s+will\s+be\b", re.IGNORECASE),
    re.compile(r"\bwe\s+have\s+reversed\b", re.IGNORECASE),
    re.compile(r"\btransaction\s+has\s+been\s+reversed\b", re.IGNORECASE),
    re.compile(r"\baccount\s+has\s+been\s+unblocked\b", re.IGNORECASE),
    re.compile(r"\bwe\s+will\s+recover\b", re.IGNORECASE),
    re.compile(r"\byour\s+money\s+has\s+been\s+recovered\b", re.IGNORECASE),
    re.compile(r"\bwe\s+will\s+return\s+your\s+(money|amount|funds)\b", re.IGNORECASE),
    re.compile(r"\byour\s+money\s+will\s+be\s+returned\b(?!\s+through\s+official\s+channels)", re.IGNORECASE),
    re.compile(r"\bwe\s+will\s+unblock\b", re.IGNORECASE),
    re.compile(r"\baccount\s+will\s+be\s+unblocked\b", re.IGNORECASE),
    re.compile(r"\bwe\s+will\s+reverse\b", re.IGNORECASE),
]

_SAFE_FINANCIAL_LANGUAGE = "any eligible amount will be returned through official channels"


def _has_unauthorized_promise(text: str) -> bool:
    """Check if text contains an unauthorized financial promise."""
    for pattern in _UNAUTHORIZED_PROMISE_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _fix_unauthorized_promise(text: str) -> str:
    """Replace unauthorized financial promises with safe language."""
    for pattern in _UNAUTHORIZED_PROMISE_PATTERNS:
        match = pattern.search(text)
        if match:
            # Replace the matched sentence with safe language
            text = pattern.sub(_SAFE_FINANCIAL_LANGUAGE, text)
    return text


# ---------------------------------------------------------------------------
# Rule 3: Suspicious Third-Party Contact Detection
# Checked on customer_reply only.
# ---------------------------------------------------------------------------

_SUSPICIOUS_THIRD_PARTY_PATTERNS = [
    # "call this number: ..."
    re.compile(r"\bcall\s+this\s+number\b", re.IGNORECASE),
    # Phone numbers that look like directions to contact
    re.compile(r"\bcontact\s+.*\+880\d+", re.IGNORECASE),
    re.compile(r"\bcall\s+.*\+880\d+", re.IGNORECASE),
    # "visit this link/website/url"
    re.compile(r"\bvisit\s+(this|the)\s+(link|website|url|page)\b", re.IGNORECASE),
    # Explicit external URLs
    re.compile(r"\bgo\s+to\s+https?://", re.IGNORECASE),
    re.compile(r"\bvisit\s+https?://", re.IGNORECASE),
    re.compile(r"\bclick\s+(on\s+)?(this|the)\s+link\b", re.IGNORECASE),
]

# Safe phrases (NOT violations per SAMPLE-04)
_SAFE_CONTACT_PHRASES = [
    "contact the merchant",
    "contacting the merchant",
    "official support channels",
    "official channels",
    "through official channels",
    "reply to this",
    "contact us",
]


def _has_suspicious_third_party(text: str) -> bool:
    """Check if text directs customer to a suspicious third party."""
    text_lower = text.lower()

    for pattern in _SUSPICIOUS_THIRD_PARTY_PATTERNS:
        match = pattern.search(text)
        if match:
            # Check if it's in a safe context
            match_text = text_lower[max(0, match.start() - 20):match.end() + 20]
            if any(safe in match_text for safe in _SAFE_CONTACT_PHRASES):
                continue
            return True
    return False


# ---------------------------------------------------------------------------
# PIN/OTP Warning Injection
# Almost every sample output includes this warning. We add it if missing.
# ---------------------------------------------------------------------------

_ENGLISH_PIN_WARNING = "Please do not share your PIN or OTP with anyone."
_BANGLA_PIN_WARNING = "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"

_PIN_WARNING_PRESENT_PATTERNS = [
    re.compile(r"do\s+not\s+share\s+(your\s+)?pin", re.IGNORECASE),
    re.compile(r"don'?t\s+share\s+(your\s+)?pin", re.IGNORECASE),
    re.compile(r"never\s+ask\s+for\s+(your\s+)?pin", re.IGNORECASE),
    re.compile(r"পিন.*শেয়ার", re.IGNORECASE),
    re.compile(r"ওটিপি.*শেয়ার", re.IGNORECASE),
]


def _has_pin_warning(text: str) -> bool:
    """Check if the text already contains a PIN/OTP warning."""
    for pattern in _PIN_WARNING_PRESENT_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _detect_language(text: str) -> str:
    """Simple heuristic to detect if reply is in Bangla or English."""
    # Count Bangla Unicode characters (Bengali block: U+0980–U+09FF)
    bangla_chars = sum(1 for c in text if "\u0980" <= c <= "\u09FF")
    total_alpha = sum(1 for c in text if c.isalpha())
    if total_alpha == 0:
        return "en"
    if bangla_chars / total_alpha > 0.3:
        return "bn"
    return "en"


# ---------------------------------------------------------------------------
# Main Safety Enforcement Function
# ---------------------------------------------------------------------------

def enforce_safety(response: Dict[str, Any], request_ticket_id: str) -> Dict[str, Any]:
    """
    Apply all deterministic safety rules to the LLM output.

    This function MUST be called on every response before it is returned.
    It modifies the response dict in-place and returns it.

    Execution order:
      1. Force-correct ticket_id echo
      2. Validate and fix enum values
      3. Rule 1: Check customer_reply for credential requests
      4. Rule 2: Check customer_reply + recommended_next_action for unauthorized promises
      5. Rule 3: Check customer_reply for suspicious third-party contact
      6. Auto-escalation (phishing → critical + fraud_risk + human_review)
      7. Add PIN/OTP warning if missing
      8. Clamp confidence to [0.0, 1.0]
    """

    # -----------------------------------------------------------------------
    # 1. Force-correct ticket_id echo
    # -----------------------------------------------------------------------
    response["ticket_id"] = request_ticket_id

    # -----------------------------------------------------------------------
    # 2. Validate and fix enum values
    # -----------------------------------------------------------------------
    if response.get("evidence_verdict") not in EVIDENCE_VERDICTS:
        response["evidence_verdict"] = "insufficient_data"

    if response.get("case_type") not in CASE_TYPES:
        response["case_type"] = "other"

    if response.get("severity") not in SEVERITIES:
        response["severity"] = "medium"

    if response.get("department") not in DEPARTMENTS:
        response["department"] = "customer_support"

    # Ensure human_review_required is a boolean
    if not isinstance(response.get("human_review_required"), bool):
        response["human_review_required"] = True  # Safer to default to True

    # -----------------------------------------------------------------------
    # 3. Rule 1: Credential Request Check (-15 pts)
    #    Field: customer_reply
    # -----------------------------------------------------------------------
    customer_reply = response.get("customer_reply", "")
    if _has_credential_request(customer_reply):
        # Rewrite the entire customer_reply to a safe version
        reply_lang = _detect_language(customer_reply)
        if reply_lang == "bn":
            response["customer_reply"] = (
                "আপনার অভিযোগ আমরা নথিভুক্ত করেছি। আমাদের দল বিষয়টি "
                "পর্যালোচনা করবে এবং অফিসিয়াল চ্যানেলে আপনাকে জানাবে। "
                + _BANGLA_PIN_WARNING
            )
        else:
            response["customer_reply"] = (
                "We have noted your concern. Our team will review the case "
                "and contact you through official support channels. "
                + _ENGLISH_PIN_WARNING
            )
        customer_reply = response["customer_reply"]

    # -----------------------------------------------------------------------
    # 4. Rule 2: Unauthorized Financial Promise Check (-10 pts)
    #    Fields: customer_reply AND recommended_next_action
    # -----------------------------------------------------------------------
    customer_reply = response.get("customer_reply", "")
    if _has_unauthorized_promise(customer_reply):
        response["customer_reply"] = _fix_unauthorized_promise(customer_reply)

    next_action = response.get("recommended_next_action", "")
    if _has_unauthorized_promise(next_action):
        response["recommended_next_action"] = _fix_unauthorized_promise(next_action)

    # -----------------------------------------------------------------------
    # 5. Rule 3: Suspicious Third-Party Contact Check (-10 pts)
    #    Field: customer_reply
    # -----------------------------------------------------------------------
    customer_reply = response.get("customer_reply", "")
    if _has_suspicious_third_party(customer_reply):
        reply_lang = _detect_language(customer_reply)
        if reply_lang == "bn":
            response["customer_reply"] = (
                "আপনার অভিযোগ আমরা নথিভুক্ত করেছি। আমাদের দল বিষয়টি "
                "পর্যালোচনা করবে এবং অফিসিয়াল চ্যানেলে আপনাকে জানাবে। "
                + _BANGLA_PIN_WARNING
            )
        else:
            response["customer_reply"] = (
                "We have noted your concern. Our team will review the case "
                "and contact you through official support channels. "
                + _ENGLISH_PIN_WARNING
            )

    # -----------------------------------------------------------------------
    # 6. Auto-Escalation Rules
    # -----------------------------------------------------------------------
    # Rule A: phishing_or_social_engineering → critical + fraud_risk + human review
    if response.get("case_type") == "phishing_or_social_engineering":
        response["severity"] = "critical"
        response["department"] = "fraud_risk"
        response["human_review_required"] = True

    # Rule B: fraud_risk department → critical + human review
    if response.get("department") == "fraud_risk":
        response["severity"] = "critical"
        response["human_review_required"] = True

    # -----------------------------------------------------------------------
    # 7. Add PIN/OTP warning if missing from customer_reply
    # -----------------------------------------------------------------------
    customer_reply = response.get("customer_reply", "")
    if customer_reply and not _has_pin_warning(customer_reply):
        reply_lang = _detect_language(customer_reply)
        if reply_lang == "bn":
            response["customer_reply"] = customer_reply.rstrip() + " " + _BANGLA_PIN_WARNING
        else:
            response["customer_reply"] = customer_reply.rstrip() + " " + _ENGLISH_PIN_WARNING

    # -----------------------------------------------------------------------
    # 8. Clamp confidence to [0.0, 1.0]
    # -----------------------------------------------------------------------
    confidence = response.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
            response["confidence"] = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            response["confidence"] = None

    # -----------------------------------------------------------------------
    # 9. Ensure relevant_transaction_id is either a string or None
    # -----------------------------------------------------------------------
    txn_id = response.get("relevant_transaction_id")
    if txn_id is not None and not isinstance(txn_id, str):
        response["relevant_transaction_id"] = None

    # -----------------------------------------------------------------------
    # 10. Ensure text fields are strings
    # -----------------------------------------------------------------------
    for field in ("agent_summary", "recommended_next_action", "customer_reply"):
        if not isinstance(response.get(field), str) or not response[field].strip():
            response[field] = "Unable to process at this time. Please contact support through official channels."

    return response
