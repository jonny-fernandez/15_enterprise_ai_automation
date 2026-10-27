"""Offline tests for Project 15 additive CP2 planning gates."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from enterprise_automation.contracts import CONTRACTS
from enterprise_automation.pipelines.cp2_upgrade import (
    evaluate_contract_evolution, dependent_order_ids,
)
from enterprise_automation.adapters.base import page_slice
from enterprise_automation.pipelines.ingestion import ingest_sources
from enterprise_automation.pipelines.cp2_pipeline import execute_cp2, _enrich
from enterprise_automation.warehouse.sqlite import SQLiteWarehouse


def test_identical_contract_is_unchanged():
    decision = evaluate_contract_evolution(CONTRACTS["ERP"], CONTRACTS["ERP"])
    assert decision.compatible and decision.status == "UNCHANGED"


def test_additive_optional_versioned_field():
    source = CONTRACTS["CRM"]
    newer = replace(source, version="crm.customers.v2", optional=("region",))
    decision = evaluate_contract_evolution(source, newer)
    assert decision.compatible and decision.status == "BACKWARD_COMPATIBLE"
    assert not decision.reasons


def test_version_only_change_is_explicit():
    old = CONTRACTS["CRM"]
    new = replace(old, version="crm.customers.v2")
    assert evaluate_contract_evolution(old, new).status == "VERSION_ONLY"


@pytest.mark.parametrize("field,value,reason", [
    ("key_field", "different", "key_field:changed"),
    ("entity", "members", "entity:changed"),
    ("source", "OTHER", "source:changed"),
    ("timestamp_field", "when", "timestamp_field:changed"),
    ("required", ("customer_id", "customer_name", "region", "updated_at_utc"), "required_fields:changed"),
    ("optional", ("customer_name",), "field_definitions:overlapping_or_duplicate"),
])
def test_breaking_contract_change(field, value, reason):
    old = CONTRACTS["CRM"]
    new = replace(old, **{field: value}, version="crm.customers.v2")
    decision = evaluate_contract_evolution(old, new)
    assert not decision.compatible and reason in decision.reasons


def test_unchanged_version_with_addition_blocked():
    old = CONTRACTS["CRM"]
    proposed = replace(old, optional=("region",))
    result = evaluate_contract_evolution(old, proposed)
    assert "version:bump_required" in result.reasons


@pytest.mark.parametrize("version", ["crm.customers.v0", "crm.customers.vgarbage", "erp.orders.v2", "crm.customers.v-1"])
def test_bad_version_family_blocked(version):
    old = CONTRACTS["CRM"]
    assert not evaluate_contract_evolution(old, replace(old, version=version)).compatible


def test_existing_field_numeric_type_change_blocked():
    old = CONTRACTS["CRM"]
    proposed = replace(old, numeric_fields=("customer_name",), version="crm.customers.v2")
    result = evaluate_contract_evolution(old, proposed)
    assert "existing_field_type:changed" in result.reasons


def test_new_optional_numeric_field_can_be_additive():
    old = CONTRACTS["CRM"]
    proposed = replace(old, optional=("synthetic_credit_limit",),
                       numeric_fields=("synthetic_credit_limit",), version="crm.customers.v2")
    assert evaluate_contract_evolution(old, proposed).compatible


def test_downgrade_blocked():
    newer = replace(CONTRACTS["CRM"], version="crm.customers.v3")
    older = replace(newer, version="crm.customers.v2")
    assert "version:downgrade" in evaluate_contract_evolution(newer, older).reasons


def _wrapper(id, customer):
    return {"record_id": id, "payload": {"order_id": id, "customer_id": customer}}


def test_dependency_refresh_unique_sorted_orders():
    records = {"ERP": [_wrapper("O2", "C1"), _wrapper("O1", "C1"), _wrapper("O3", "C2")],
               "CRM": [], "TICKETING": []}
    selected = {"ERP": [], "CRM": [{"payload": {"customer_id": "C1"}}], "TICKETING": []}
    assert dependent_order_ids(records, selected) == ["O1", "O2"]


def test_ticket_change_refreshes_related_customer_orders():
    records = {"ERP": [_wrapper("O1", "C1"), _wrapper("O2", "C2")], "CRM": [], "TICKETING": []}
    selected = {"ERP": [], "CRM": [], "TICKETING": [{"payload": {"customer_id": "C2"}}]}
    assert dependent_order_ids(records, selected) == ["O2"]


def test_unrelated_update_does_not_refresh():
    records = {"ERP": [_wrapper("O1", "C1")], "CRM": [], "TICKETING": []}
    selected = {"ERP": [], "CRM": [], "TICKETING": [{"payload": {"customer_id": "C9"}}]}
    assert dependent_order_ids(records, selected) == []


@pytest.mark.parametrize("invalid", [True, 0, -1, 1.1, "10"])
def test_refresh_limit_must_be_positive_integer(invalid):
    records = {"ERP": [], "CRM": [], "TICKETING": []}
    selected = {"ERP": [], "CRM": [], "TICKETING": []}
    with pytest.raises(ValueError):
        dependent_order_ids(records, selected, max_affected_orders=invalid)


def test_refresh_limit_blocks_large_driven_rebuild():
    records = {"ERP": [_wrapper("O1", "C1"), _wrapper("O2", "C1")], "CRM": [], "TICKETING": []}
    selected = {"ERP": [], "CRM": [{"payload": {"customer_id": "C1"}}], "TICKETING": []}
    with pytest.raises(ValueError, match="safe driver limit"):
        dependent_order_ids(records, selected, max_affected_orders=1)


def test_invalid_customer_id_rejected():
    with pytest.raises(ValueError, match="customer_id"):
        dependent_order_ids({"ERP": [], "CRM": [], "TICKETING": []},
                            {"ERP": [], "CRM": [{"payload": {"customer_id": ""}}], "TICKETING": []})


class Source:
    def __init__(self, name, source_type, data):
        self.source_system = name
        self.source_type = source_type
        self.data = data
    def list_page(self, *, cursor=0, page_size=2):
        return page_slice(self.data, cursor=cursor, page_size=page_size)


def _sources(name="Ada", tickets=1, updated="2026-10-15T00:00:00Z"):
    stamp = "2026-10-15T00:00:00Z"
    return [
        Source("ERP", "simulated_api", [
            {"order_id": "O1", "customer_id": "C1", "amount_usd": "24.50", "updated_at_utc": stamp},
            {"order_id": "O2", "customer_id": "C2", "amount_usd": "11.00", "updated_at_utc": stamp}]),
        Source("CRM", "simulated_api", [
            {"customer_id": "C1", "customer_name": name, "updated_at_utc": updated},
            {"customer_id": "C2", "customer_name": "Bea", "updated_at_utc": stamp}]),
        Source("TICKETING", "csv_file_drop", [
            {"ticket_id": f"T{i}", "customer_id": "C1", "priority": "high", "updated_at_utc": updated}
            for i in range(1, tickets + 1)]),
    ]


class FakeReader:
    def __init__(self, owner):self.owner = owner
    def parquet(self, path):return self
    def count(self):return self.owner.count

class FakeSpark:
    def __init__(self):
        self.count = 0
        self.read = FakeReader(self)
        self.single_modes = []


@pytest.fixture
def local_engine(monkeypatch):
    from enterprise_automation.pipelines import spark_transform
    spark = FakeSpark()
    def writer(_, rows, destination, *, single_file=True):
        spark.single_modes.append(single_file)
        path = Path(destination)
        path.mkdir(parents=True)
        (path / "synthetic_only.parquet").write_text(str(len(rows)), encoding="utf-8")
        spark.count = len(rows)
        return len(rows)
    monkeypatch.setattr(spark_transform, "write_enriched_parquet", writer)
    monkeypatch.setattr(spark_transform, "spark_joined_records", lambda session, data: _enrich(data)[0])
    return spark


def test_new_options_reject_invalid_modes(tmp_path):
    for kwargs in [{"refresh_related_orders": 1}, {"spark_output_mode": "unknown"}]:
        with pytest.raises(ValueError):
            execute_cp2(root=tmp_path, source_run_id="src", run_id="new", **kwargs)
    assert not (tmp_path / "artifacts" / "cp2_local_warehouse.sqlite").exists()


def test_refresh_unchanged_order_after_crm_ticket_change(tmp_path, local_engine):
    ingest_sources(sources=_sources(), root=tmp_path, run_id="src1", ingested_at_utc="2026-10-15T00:00:00Z")
    first = execute_cp2(root=tmp_path, source_run_id="src1", run_id="one", spark=local_engine)
    assert first["rows_written_parquet"] == 2
    # Entire current snapshot is present in src2, but ERP records are unchanged.
    ingest_sources(sources=_sources(name="Ada Updated", tickets=2, updated="2026-10-16T00:00:00Z"),
                   root=tmp_path, run_id="src2", ingested_at_utc="2026-10-16T00:00:00Z")
    second = execute_cp2(root=tmp_path, source_run_id="src2", run_id="two", spark=local_engine,
                         refresh_related_orders=True, spark_output_mode="partitioned")
    assert second["rows_written_parquet"] == 1
    assert second["selection"]["ERP"]["selected"] == 0
    assert second["upgrade_options"]["dependent_refresh_orders"] == 1
    assert local_engine.single_modes == [True, False]
    warehouse = SQLiteWarehouse(tmp_path / "artifacts" / "cp2_local_warehouse.sqlite")
    try:
        refreshed = warehouse.conn.execute("SELECT customer_name,ticket_count FROM orders WHERE order_id='O1'").fetchone()
        untouched = warehouse.conn.execute("SELECT customer_name,ticket_count FROM orders WHERE order_id='O2'").fetchone()
        assert tuple(refreshed) == ("Ada Updated", 2)
        assert tuple(untouched) == ("Bea", 0)
    finally:
        warehouse.close()
    replay = execute_cp2(root=tmp_path, source_run_id="src2", run_id="two", spark=local_engine,
                         refresh_related_orders=True, spark_output_mode="partitioned")
    assert replay["replay_status"] == "duplicate_skipped"
    with pytest.raises(ValueError, match="different inputs"):
        execute_cp2(root=tmp_path, source_run_id="src2", run_id="two", spark=local_engine)


def test_synthetic_benchmark_deterministic(tmp_path):
    from scripts.project15_cp2_benchmark import benchmark
    a = benchmark(customers=4, orders=100, tickets=20, seed=15)
    b = benchmark(customers=4, orders=100, tickets=20, seed=15)
    assert a["deterministic_result_sha256"] == b["deterministic_result_sha256"]
    assert a["enriched_orders"] == 100
    assert a["quality"]["tickets_total"] == 20
    assert a["execution_mode"] == "local_synthetic_python_only"


def test_synthetic_benchmark_different_seed_changes_hash():
    from scripts.project15_cp2_benchmark import benchmark
    assert benchmark(customers=4, orders=20, tickets=8, seed=15)["deterministic_result_sha256"] != (
        benchmark(customers=4, orders=20, tickets=8, seed=16)["deterministic_result_sha256"])


def test_synthetic_row_generation_rejects_bools():
    from scripts.project15_cp2_benchmark import generate_synthetic_snapshot
    with pytest.raises(ValueError):
        generate_synthetic_snapshot(customers=True)
