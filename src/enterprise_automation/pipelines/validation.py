def validate_required_fields(record: dict, required: set[str]) -> list[str]:
    return sorted(field for field in required if record.get(field) in (None, ""))
