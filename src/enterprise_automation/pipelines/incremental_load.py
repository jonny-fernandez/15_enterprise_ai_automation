"""Timezone-correct timestamp comparisons; watermark persistence belongs to CP2."""
from datetime import datetime, timezone


def parse_timestamp(value: str, *, require_timezone: bool = False) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Timestamp must be a nonempty ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Timestamp must be valid ISO 8601") from exc
    if parsed.tzinfo is None:
        if require_timezone:
            raise ValueError("Timestamp must include an explicit timezone")
        # Backward compatibility with the starter's timezone-naive fixture.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_newer_than_watermark(event_timestamp: str, watermark: str) -> bool:
    return parse_timestamp(event_timestamp) > parse_timestamp(watermark)
