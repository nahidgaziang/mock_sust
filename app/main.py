"""
FastAPI application for QueueStorm Investigator API.

Endpoints:
  GET  /health         → {"status": "ok"}
  POST /analyze-ticket → Structured investigation response
"""

from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.investigator import analyze_ticket
from app.safety import enforce_safety
from app.schemas import AnalyzeTicketRequest, AnalyzeTicketResponse

# ---------------------------------------------------------------------------
# Logging setup — logs to stderr, never to response body
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("queuestorm")

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="QueueStorm Investigator",
    description="AI-powered complaint investigation API for digital finance support.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Error Handlers — never expose stack traces, tokens, or secrets
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors → 422."""
    # Extract safe error messages (field names only, no values)
    errors = []
    for error in exc.errors():
        loc = " → ".join(str(l) for l in error.get("loc", []))
        msg = error.get("msg", "Invalid value")
        errors.append(f"{loc}: {msg}")

    return JSONResponse(
        status_code=422,
        content={"error": "Validation error", "details": errors},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catch-all: never expose internals."""
    logger.error("Unhandled exception: %s", traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Health check endpoint. Must respond within 60 seconds of service start."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /analyze-ticket
# ---------------------------------------------------------------------------

@app.post("/analyze-ticket", response_model=AnalyzeTicketResponse)
async def analyze_ticket_endpoint(request: AnalyzeTicketRequest):
    """
    Analyze a customer complaint ticket.

    Accepts the ticket with optional transaction history,
    runs LLM-powered investigation, applies safety guardrails,
    and returns a structured response.
    """

    # Validate complaint is not empty
    if not request.complaint or not request.complaint.strip():
        raise HTTPException(
            status_code=422,
            detail="Complaint text cannot be empty.",
        )

    try:
        # Step 1: Run the investigator engine (LLM call)
        raw_result = await analyze_ticket(request)

        # Step 2: Apply deterministic safety guardrails
        safe_result = enforce_safety(raw_result, request.ticket_id)

        # Step 3: Validate through Pydantic model (guarantees schema correctness)
        response = AnalyzeTicketResponse(**safe_result)

        return response

    except Exception as e:
        # Log the error but never expose it
        logger.error("Error analyzing ticket %s: %s", request.ticket_id, traceback.format_exc())

        # Return a safe fallback response instead of a 500
        # This ensures valid requests NEVER get a 500
        fallback = {
            "ticket_id": request.ticket_id,
            "relevant_transaction_id": None,
            "evidence_verdict": "insufficient_data",
            "case_type": "other",
            "severity": "medium",
            "department": "customer_support",
            "agent_summary": "Unable to fully analyze the complaint at this time. Manual review required.",
            "recommended_next_action": "Route to customer support for manual investigation of this ticket.",
            "customer_reply": (
                "Thank you for reaching out. Our team will review your concern "
                "and contact you through official support channels. "
                "Please do not share your PIN or OTP with anyone."
            ),
            "human_review_required": True,
            "confidence": 0.0,
            "reason_codes": ["fallback", "manual_review_required"],
        }

        # Apply safety to fallback too (belt and suspenders)
        safe_fallback = enforce_safety(fallback, request.ticket_id)
        return AnalyzeTicketResponse(**safe_fallback)
