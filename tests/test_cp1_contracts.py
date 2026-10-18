import pytest
from enterprise_automation.contracts import CONTRACTS, validate_record
from enterprise_automation.pipelines.incremental_load import is_newer_than_watermark, parse_timestamp


def test_contracts_are_versioned_and_independent():
    assert set(CONTRACTS) == {"ERP", "CRM", "TICKETING"}
    assert len({c.version for c in CONTRACTS.values()}) == 3
    assert len({c.key_field for c in CONTRACTS.values()}) >= 2


def test_valid_erp_record():
    record = {"order_id": "O-1", "customer_id": "C-1", "amount_usd": 1.25,
              "updated_at_utc": "2026-10-16T00:00:00Z"}
    assert validate_record(record, CONTRACTS["ERP"]) == []


@pytest.mark.parametrize("value", [-1, "bad", float("inf"), True])
def test_bad_money_rejected(value):
    record = {"order_id": "O-1", "customer_id": "C-1", "amount_usd": value,
              "updated_at_utc": "2026-10-16T00:00:00Z"}
    assert validate_record(record, CONTRACTS["ERP"])


def test_schema_drift_extra_fields_rejected_without_values():
    record = {"order_id": "O-1", "customer_id": "C-1", "amount_usd": 3,
              "updated_at_utc": "2026-10-16T00:00:00Z", "secret": "DO_NOT_LEAK"}
    assert validate_record(record, CONTRACTS["ERP"]) == ["secret:unexpected_field"]


def test_timezone_required_in_contract():
    record = {"customer_id": "C-1", "customer_name": "Synthetic",
              "updated_at_utc": "2026-10-16T00:00:00"}
    assert "updated_at_utc:invalid_utc_timestamp" in validate_record(record, CONTRACTS["CRM"])


def test_timestamp_compares_in_utc_not_lexicographically():
    assert not is_newer_than_watermark("2026-10-16T10:00:00+03:00", "2026-10-16T08:30:00Z")
    assert is_newer_than_watermark("2026-10-16T11:00:00+03:00", "2026-10-16T07:30:00Z")


def test_malformed_timestamps_fail_closed():
    with pytest.raises(ValueError):
        parse_timestamp("not-a-date")


def test_non_utc_zone_rejected_for_utc_contract_field():
    record = {"customer_id": "C-1", "customer_name": "Synthetic",
              "updated_at_utc": "2026-10-16T02:00:00+02:00"}
    assert "updated_at_utc:invalid_utc_timestamp" in validate_record(record, CONTRACTS["CRM"])
