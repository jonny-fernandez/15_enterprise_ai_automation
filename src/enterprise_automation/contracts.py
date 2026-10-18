"""Deterministic, versioned data contracts for synthetic portfolio fixtures.

Business rules remain independent of AI and all real external systems.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

from enterprise_automation.pipelines.incremental_load import parse_timestamp


@dataclass(frozen=True)
class SourceContract:
    source: str
    entity: str
    version: str
    key_field: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    numeric_fields: tuple[str, ...] = ()
    timestamp_field: str = "updated_at_utc"


CONTRACTS: Mapping[str, SourceContract] = {
    "ERP": SourceContract(
        "ERP", "orders", "erp.orders.v1", "order_id",
        ("order_id", "customer_id", "amount_usd", "updated_at_utc"),
        numeric_fields=("amount_usd",),
    ),
    "CRM": SourceContract(
        "CRM", "customers", "crm.customers.v1", "customer_id",
        ("customer_id", "customer_name", "updated_at_utc"),
    ),
    "TICKETING": SourceContract(
        "TICKETING", "tickets", "ticketing.tickets.v1", "ticket_id",
        ("ticket_id", "customer_id", "priority", "updated_at_utc"),
    ),
}


def validate_record(record: dict, contract: SourceContract) -> list[str]:
    """Return field-level error labels only; never include sensitive values."""
    errors = []
    if not isinstance(record, dict):
        return ["record:invalid_object"]
    allowed = set(contract.required) | set(contract.optional)
    for field in sorted(set(record) - allowed):
        errors.append(f"{field}:unexpected_field")
    for field in contract.required:
        value = record.get(field)
        if value is None or isinstance(value, (list, dict, bool)) or (isinstance(value, str) and not value.strip()):
            errors.append(f"{field}:missing_or_invalid")
        elif field not in contract.numeric_fields and not isinstance(value, str):
            errors.append(f"{field}:must_be_string")
    for field in contract.numeric_fields:
        value = record.get(field)
        if value is None or isinstance(value, bool):
            continue
        try:
            amount = Decimal(str(value))
            if not amount.is_finite() or amount < 0:
                errors.append(f"{field}:nonfinite_or_negative")
        except (InvalidOperation, ValueError):
            errors.append(f"{field}:invalid_number")
    timestamp = record.get(contract.timestamp_field)
    if isinstance(timestamp, str) and timestamp.strip():
        try:
            parsed = parse_timestamp(timestamp, require_timezone=True)
            if timestamp.endswith("Z") is False and datetime.fromisoformat(timestamp).utcoffset().total_seconds() != 0:
                raise ValueError("Expected UTC offset")
        except ValueError:
            errors.append(f"{contract.timestamp_field}:invalid_utc_timestamp")
    return sorted(set(errors))
