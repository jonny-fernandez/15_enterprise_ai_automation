from enterprise_automation.pipelines.validation import validate_required_fields
from enterprise_automation.pipelines.incremental_load import is_newer_than_watermark
from enterprise_automation.events.retry_policy import retryable_status

def test_required_field_validation():
    assert validate_required_fields({"id": "1"}, {"id", "timestamp"}) == ["timestamp"]

def test_watermark():
    assert is_newer_than_watermark("2026-10-08T10:00:00", "2026-10-08T09:00:00")

def test_retry_policy():
    assert retryable_status(429)
    assert not retryable_status(400)
