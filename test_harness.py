"""
Integration test harness for QueueStorm Investigator API.

Reads all 10 sample cases, hits the FastAPI endpoint directly using AsyncClient,
and validates HTTP status, schema, safety rules, and reasoning outcomes.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.main import app
from app.schemas import AnalyzeTicketResponse

# Safety rule patterns for testing
import re

_CREDENTIAL_REQUEST_PATTERNS = [
    re.compile(r"\bprovide\s+(us\s+)?(your\s+)?(pin|otp|password|card\s*number)", re.IGNORECASE),
    re.compile(r"\benter\s+(your\s+)?(pin|otp|password)", re.IGNORECASE),
    re.compile(r"\bsend\s+(us\s+|me\s+)?(your\s+)?(otp|pin|password)", re.IGNORECASE),
    re.compile(r"\bgive\s+(us\s+|me\s+)?(your\s+)?(pin|otp|password|card)", re.IGNORECASE),
]

_UNAUTHORIZED_PROMISE_PATTERNS = [
    re.compile(r"\bwe\s+will\s+refund\b", re.IGNORECASE),
    re.compile(r"\bwe\s+have\s+reversed\b", re.IGNORECASE),
    re.compile(r"\baccount\s+has\s+been\s+unblocked\b", re.IGNORECASE),
]

def check_safety(response_json: dict) -> list:
    errors = []
    reply = response_json.get("customer_reply", "")
    next_action = response_json.get("recommended_next_action", "")
    
    # Check Rule 1 (Credential Request)
    for p in _CREDENTIAL_REQUEST_PATTERNS:
        if p.search(reply):
            errors.append(f"Rule 1 Violation (Credential Request) found in reply: '{reply}'")
            
    # Check Rule 2 (Unauthorized Promise)
    for p in _UNAUTHORIZED_PROMISE_PATTERNS:
        if p.search(reply):
            errors.append(f"Rule 2 Violation (Unauthorized Promise) found in reply: '{reply}'")
        if p.search(next_action):
            errors.append(f"Rule 2 Violation (Unauthorized Promise) found in next_action: '{next_action}'")
            
    return errors


async def run_tests():
    sample_file = Path("Preliminary Questions and Resources/SUST_Preli_Sample_Cases.json")
    if not sample_file.exists():
        print(f"ERROR: Cannot find {sample_file}")
        sys.exit(1)

    with open(sample_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    cases = data.get("cases", [])
    if not cases:
        print("ERROR: No cases found in the sample file.")
        sys.exit(1)

    print(f"Loaded {len(cases)} sample cases. Running tests...\n")
    print("-" * 80)

    passed_count = 0
    
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # First check health
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json() == {"status": "ok"}
        
        for case in cases:
            case_id = case["id"]
            label = case["label"]
            input_data = case["input"]
            expected = case["expected_output"]
            
            print(f"Testing {case_id}: {label}")
            
            response = await client.post("/analyze-ticket", json=input_data)
            
            if response.status_code != 200:
                print(f"  FAIL: HTTP Status {response.status_code}")
                print(f"     Body: {response.text}")
                continue
                
            resp_json = response.json()
            
            # Check Schema
            try:
                AnalyzeTicketResponse(**resp_json)
            except ValidationError as e:
                print(f"  FAIL: Schema Validation Error")
                print(f"     {e}")
                continue
                
            # Check ID Echo
            if resp_json.get("ticket_id") != input_data["ticket_id"]:
                print(f"  FAIL: ticket_id mismatch. Expected {input_data['ticket_id']}, got {resp_json.get('ticket_id')}")
                continue
                
            # Check Safety Rules
            safety_errors = check_safety(resp_json)
            if safety_errors:
                print(f"  FAIL: Safety Violations")
                for err in safety_errors:
                    print(f"     - {err}")
                continue

            # Check Reasoning (Compare with expected)
            mismatches = []
            for field in ["case_type", "evidence_verdict", "department", "severity"]:
                if resp_json.get(field) != expected.get(field):
                    mismatches.append(f"{field}: expected {expected.get(field)}, got {resp_json.get(field)}")
                    
            if mismatches:
                print(f"  WARNING: Reasoning differences:")
                for m in mismatches:
                    print(f"     - {m}")
                
            print(f"  PASS")
            passed_count += 1
            print("-" * 80)

    print(f"\nTest Summary: {passed_count}/{len(cases)} cases passed basic checks (schema, safety, 200 OK).")

if __name__ == "__main__":
    # If no LLM API key is present, the fallback logic will trigger.
    # The fallback should pass the basic schema and safety checks!
    asyncio.run(run_tests())
