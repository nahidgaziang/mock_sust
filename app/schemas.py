"""
Pydantic v2 models for QueueStorm Investigator API.

All output enums are hardcoded EXACTLY as specified in the Problem Statement Section 7.
Input enums are typed as Optional[str] to accept unknown values from hidden tests.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Output enum value sets — used by Literal types for strict enforcement
# ---------------------------------------------------------------------------

EVIDENCE_VERDICTS = ("consistent", "inconsistent", "insufficient_data")

CASE_TYPES = (
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
)

SEVERITIES = ("low", "medium", "high", "critical")

DEPARTMENTS = (
    "customer_support",
    "dispute_resolution",
    "payments_ops",
    "merchant_operations",
    "agent_operations",
    "fraud_risk",
)


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class TransactionEntry(BaseModel):
    """A single transaction in the customer's recent history."""

    transaction_id: str
    timestamp: str  # ISO 8601
    type: str       # One of: transfer, payment, cash_in, cash_out, settlement, refund
    amount: float
    counterparty: str
    status: str     # One of: completed, failed, pending, reversed


class AnalyzeTicketRequest(BaseModel):
    """
    POST /analyze-ticket request body.

    Required: ticket_id, complaint
    Optional: language, channel, user_type, campaign_context, transaction_history, metadata
    """

    ticket_id: str
    complaint: str
    language: Optional[str] = None
    channel: Optional[str] = None
    user_type: Optional[str] = None
    campaign_context: Optional[str] = None
    transaction_history: Optional[List[TransactionEntry]] = None
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Response Model
# ---------------------------------------------------------------------------

class AnalyzeTicketResponse(BaseModel):
    """
    POST /analyze-ticket response body.

    10 required fields + 2 optional fields.
    All enum fields use Literal types for strict validation.
    """

    ticket_id: str

    relevant_transaction_id: Optional[str] = None

    evidence_verdict: Literal[
        "consistent",
        "inconsistent",
        "insufficient_data",
    ]

    case_type: Literal[
        "wrong_transfer",
        "payment_failed",
        "refund_request",
        "duplicate_payment",
        "merchant_settlement_delay",
        "agent_cash_in_issue",
        "phishing_or_social_engineering",
        "other",
    ]

    severity: Literal["low", "medium", "high", "critical"]

    department: Literal[
        "customer_support",
        "dispute_resolution",
        "payments_ops",
        "merchant_operations",
        "agent_operations",
        "fraud_risk",
    ]

    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool

    # Optional fields
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reason_codes: Optional[List[str]] = None
