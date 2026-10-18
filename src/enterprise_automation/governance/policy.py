"""Deterministic source-contract guardrails and mock AI escalation."""
import hashlib
import json
import re

ALLOWED_SYSTEMS = {"ERP", "CRM", "TICKETING", "FINANCE", "RETAIL"}
CODES = {"schema_drift", "duplicate_conflict", "unmatched_entity", "timeout", "source_outage"}
OUTCOMES = {"propose_manual_review", "reject"}
TOKEN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def event_contract(event: dict) -> dict:
    """No free-form records, names, email or private source content are accepted."""
    if not isinstance(event, dict) or set(event) != {"event_id", "source", "record_ref", "scenario", "reason_code"}:
        raise ValueError("Unexpected event fields")
    if (type(event["event_id"]) is not str or type(event["record_ref"]) is not str or
        not TOKEN.fullmatch(event["event_id"]) or
        not TOKEN.fullmatch(event["record_ref"]) or
        event["source"] not in ALLOWED_SYSTEMS or
        event["scenario"] not in {"success", "transient", "permanent", "review"} or
        event["reason_code"] not in CODES):
        raise ValueError("Event contract rejected")
    if len(canonical(event)) > 1024:
        raise ValueError("Oversized event")
    return dict(event)


def mock_ai_suggestion(event: dict) -> dict:
    """No model call. Mimics a constrained AI recommendation for review testing."""
    e = event_contract(event)
    return {"schema_version": "cp3.suggestion.v1", "event_id": e["event_id"],
            "evidence_sha256": digest(e), "reason_code": e["reason_code"],
            "recommendation": "propose_manual_review", "provider": "deterministic_mock_no_llm"}


def validate_ai_suggestion(event: dict, suggestion: dict) -> dict:
    e = event_contract(event)
    if (not isinstance(suggestion, dict) or
        set(suggestion) != {"schema_version", "event_id", "evidence_sha256", "reason_code", "recommendation", "provider"} or
        suggestion["schema_version"] != "cp3.suggestion.v1" or
        suggestion["event_id"] != e["event_id"] or
        suggestion["evidence_sha256"] != digest(e) or
        suggestion["reason_code"] != e["reason_code"] or
        suggestion["recommendation"] not in OUTCOMES or
        suggestion["provider"] != "deterministic_mock_no_llm"):
        raise ValueError("Unsupported AI proposal or missing evidence")
    return dict(suggestion)
