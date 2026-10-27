"""Optional Project 15 CP2 compatibility and change-impact planning.

All functions are local, deterministic, read-only and synthetic-only.
No automatic conversion to production streaming/distributed ingestion is implied.
"""
from dataclasses import dataclass
import re
from enterprise_automation.contracts import SourceContract


@dataclass(frozen=True)
class ContractDecision:
    status: str
    reasons: tuple[str, ...]
    old_version: str
    proposed_version: str

    @property
    def compatible(self) -> bool:
        return self.status != "BREAKING"


def evaluate_contract_evolution(original: SourceContract, proposed: SourceContract) -> ContractDecision:
    """Permit only explicitly versioned, additive optional fields.

    New required fields, changed keys, and deleted/type-changed existing fields
    require a separate migration. This decision does NOT activate a new schema.
    """
    reasons = []
    for field in ("source", "entity", "key_field", "timestamp_field"):
        if getattr(original, field) != getattr(proposed, field):
            reasons.append(f"{field}:changed")
    before_req, after_req = set(original.required), set(proposed.required)
    before_opt, after_opt = set(original.optional), set(proposed.optional)
    if before_req != after_req:
        reasons.append("required_fields:changed")
    if not before_opt.issubset(after_opt):
        reasons.append("optional_fields:removed_or_promoted")
    if not set(original.numeric_fields).issubset(proposed.numeric_fields):
        reasons.append("existing_numeric_fields:removed")
    if (set(proposed.numeric_fields) - set(original.numeric_fields)) & (before_req | before_opt):
        reasons.append("existing_field_type:changed")
    if any(x not in (after_req | after_opt) for x in proposed.numeric_fields):
        reasons.append("numeric_fields:unrecognized")
    if after_req & after_opt or len(proposed.required) != len(after_req) or len(proposed.optional) != len(after_opt):
        reasons.append("field_definitions:overlapping_or_duplicate")
    def parse_version(contract):
        match = re.fullmatch(r"(.+)\.v([1-9][0-9]*)", contract.version)
        return (match.group(1), int(match.group(2))) if match else None
    prior, newer = parse_version(original), parse_version(proposed)
    if prior is None or newer is None or prior[0] != newer[0]:
        reasons.append("version:invalid_family")
    else:
        changed = (before_opt != after_opt or before_req != after_req or
                   original.numeric_fields != proposed.numeric_fields or
                   any(getattr(original, f) != getattr(proposed, f)
                       for f in ("source", "entity", "key_field", "timestamp_field")))
        if changed and newer[1] <= prior[1]:
            reasons.append("version:bump_required")
        elif newer[1] < prior[1]:
            reasons.append("version:downgrade")
    if reasons:
        return ContractDecision("BREAKING", tuple(sorted(set(reasons))), original.version, proposed.version)
    if original == proposed:
        status = "UNCHANGED"
    else:
        status = "BACKWARD_COMPATIBLE" if before_opt != after_opt else "VERSION_ONLY"
    return ContractDecision(status, (), original.version, proposed.version)


def dependent_order_ids(records: dict[str, list[dict]], selected: dict[str, list[dict]],
                        *, max_affected_orders: int = 100_000) -> list[str]:
    """Identify ERP orders to refresh after accepted CRM/ticket changes.

    Requires full current ERP snapshot. Cannot infer deleted ticket IDs or a
    ticket's *previous* customer assignment; those need a full reload.
    """
    if type(max_affected_orders) is not int or max_affected_orders < 1:
        raise ValueError("max_affected_orders must be positive integer")
    changed_customers = set()
    for system in ("CRM", "TICKETING"):
        for row in selected[system]:
            cid = row["payload"]["customer_id"]
            if not isinstance(cid, str) or not cid:
                raise ValueError("Invalid customer_id in accepted change")
            changed_customers.add(cid)
    impacted = sorted({row["payload"]["order_id"] for row in records["ERP"]
                      if row["payload"]["customer_id"] in changed_customers})
    if len(impacted) > max_affected_orders:
        raise ValueError("Dependent refresh exceeds safe driver limit; use controlled full rebuild")
    return impacted
