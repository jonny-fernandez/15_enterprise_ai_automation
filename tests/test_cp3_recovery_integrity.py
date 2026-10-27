"""Offline, opt-in CP3 recovery and negative evidence tests."""
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from enterprise_automation.adapters.base import page_slice
from enterprise_automation.pipelines.ingestion import ingest_sources
from enterprise_automation.pipelines.cp2_pipeline import execute_cp2, _enrich
from enterprise_automation.reliability.cp3_recovery import (
    inspect_committed_run, recovery_status, quality_gate, check_repeatability,
)


class Source:
    def __init__(self, source, source_type, rows):
        self.source_system = source
        self.source_type = source_type
        self.rows = rows

    def list_page(self, *, cursor=0, page_size=2):
        return page_slice(self.rows, cursor=cursor, page_size=page_size)


class FakeReader:
    def __init__(self, owner):
        self.owner = owner

    def parquet(self, _: str):
        return self

    def count(self):
        return self.owner.count


class FakeSpark:
    def __init__(self):
        self.count = 0
        self.read = FakeReader(self)


@pytest.fixture
def fake_spark(monkeypatch):
    from enterprise_automation.pipelines import spark_transform
    spark = FakeSpark()

    def write(_spark, records, output, *, single_file=True):
        path = Path(output)
        path.mkdir(parents=True, exist_ok=False)
        (path / "part-00000.parquet").write_bytes(b"SYNTHETIC_STUB" + str(len(records)).encode())
        spark.count = len(records)
        return len(records)

    monkeypatch.setattr(spark_transform, "write_enriched_parquet", write)
    monkeypatch.setattr(spark_transform, "spark_joined_records", lambda _, records: _enrich(records)[0])
    return spark


@pytest.fixture
def case(tmp_path, fake_spark):
    stamp = "2026-10-20T12:00:00Z"
    sources = [
        Source("ERP", "simulated_api", [{"order_id": "O1", "customer_id": "C1", "amount_usd": "42.50", "updated_at_utc": stamp}]),
        Source("CRM", "simulated_api", [{"customer_id": "C1", "customer_name": "Synthetic User", "updated_at_utc": stamp}]),
        Source("TICKETING", "csv_file_drop", [{"ticket_id": "T1", "customer_id": "C1", "priority": "low", "updated_at_utc": stamp}]),
    ]
    ingest_sources(sources=sources, root=tmp_path, run_id="s1", ingested_at_utc=stamp)
    output = execute_cp2(root=tmp_path, source_run_id="s1", run_id="r1", spark=fake_spark)
    return tmp_path, fake_spark, output


def _manifest(root):
    return root / "data" / "processed" / "r1" / "cp2_manifest.json"


def _json_change(root, fn):
    path = _manifest(root)
    value = json.loads(path.read_text())
    fn(value)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def test_happy_committed_run(case):
    root, _, original = case
    summary = inspect_committed_run(root, "r1")
    assert summary["status"] == "PASS"
    assert summary["input_verification"] == "full"
    assert summary["parquet_rows"] == original["rows_written_parquet"] == 1
    assert len(summary["parquet_files"]) == 1


def test_readonly_does_not_change_data(case):
    root, _, _ = case
    paths = [_manifest(root), root / "artifacts" / "cp2_local_warehouse.sqlite"]
    hashes_before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    inspect_committed_run(root, "r1")
    check_repeatability(root, "r1")
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths] == hashes_before


def test_repeatability_does_not_claim_pipeline_replay(case):
    report = check_repeatability(case[0], "r1")
    assert report["status"] == "PASS"
    assert "does not verify idempotent execution" in report["note"].lower()


@pytest.mark.parametrize("bad", ["../r1", "R 1", "", "/r1", "r1/../evil", "r" * 65])
def test_bad_run_identifier_blocked(tmp_path, bad):
    with pytest.raises(ValueError, match="identifier"):
        recovery_status(tmp_path, bad)
    assert not (tmp_path / "artifacts").exists()


def test_uncommitted_absent_run_is_new(tmp_path):
    status = recovery_status(tmp_path, "new")
    assert status.status == "NEW" and not status.committed


def test_missing_committed_run_blocked(case):
    root, _, _ = case
    with pytest.raises(ValueError, match="not committed"):
        inspect_committed_run(root, "other")


def test_healthy_run_is_immutable(case):
    assert recovery_status(case[0], "r1").status == "COMMITTED_VERIFY"


def test_manifest_mutation_blocked(case):
    root, _, _ = case
    _json_change(root, lambda m: m.update({"rows_written_parquet": 42}))
    with pytest.raises(ValueError):
        inspect_committed_run(root, "r1")


def test_db_manifest_mutation_blocked(case):
    root, _, _ = case
    db = sqlite3.connect(root / "artifacts" / "cp2_local_warehouse.sqlite")
    with db:
        db.execute("UPDATE runs SET source_run_id='changed' WHERE run_id='r1'")
    db.close()
    with pytest.raises(ValueError, match="identity"):
        inspect_committed_run(root, "r1")


def test_raw_source_mutation_blocked(case):
    root, _, _ = case
    raw = root / "data" / "raw" / "s1" / "erp.jsonl"
    raw.write_bytes(raw.read_bytes() + b"fake\n")
    with pytest.raises(ValueError, match="hash"):
        inspect_committed_run(root, "r1")


def test_parquet_mutation_blocked(case):
    root, _, _ = case
    part = root / "data" / "processed" / "r1" / "parquet" / "part-00000.parquet"
    part.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest"):
        inspect_committed_run(root, "r1")


def test_unlisted_parquet_blocked(case):
    root, _, _ = case
    part = root / "data" / "processed" / "r1" / "parquet" / "extra.parquet"
    part.write_bytes(b"extra")
    with pytest.raises(ValueError, match="unlisted"):
        inspect_committed_run(root, "r1")


def test_missing_parquet_blocked(case):
    root, _, _ = case
    (root / "data" / "processed" / "r1" / "parquet" / "part-00000.parquet").unlink()
    with pytest.raises(ValueError, match="missing"):
        inspect_committed_run(root, "r1")


def test_part_symlink_blocked(case):
    root, _, _ = case
    part = root / "data" / "processed" / "r1" / "parquet" / "part-00000.parquet"
    moved = part.with_suffix(".bak")
    part.rename(moved)
    try:
        part.symlink_to(moved)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink permission unavailable")
    with pytest.raises(ValueError, match="Symlink"):
        inspect_committed_run(root, "r1")


def test_uncommitted_interruption_classified_without_mutation(case):
    root, _, _ = case
    partial = root / "data" / "processed" / "rerun"
    partial.mkdir()
    (partial / "parquet").mkdir()
    s = recovery_status(root, "rerun")
    assert s.status == "RETRY_WITH_SAME_INPUT"
    assert partial.exists()


def test_uncommitted_unexpected_file_requires_manual_review(case):
    root, _, _ = case
    partial = root / "data" / "processed" / "rerun"
    partial.mkdir()
    (partial / "important.txt").write_text("do not delete")
    assert recovery_status(root, "rerun").status == "MANUAL_REVIEW"
    assert (partial / "important.txt").exists()


def test_json_invalid_part_path_blocked(case):
    root, _, _ = case
    _json_change(root, lambda m: m["parquet_files"][0].update({"path": "../fake.parquet"}))
    with pytest.raises(ValueError):
        inspect_committed_run(root, "r1")


def test_quality_gate_pass(case):
    assert quality_gate(case[2])["status"] == "PASS"


@pytest.mark.parametrize("counts", [(5, 6), (-1, 0), (5, -1), (True, 0), (5, True)])
def test_quality_invalid_counts_fail_closed(case, counts):
    val = dict(case[2]);val["reconciliation"] = {"orders_total": counts[0], "orders_unmatched_customers": counts[1]}
    with pytest.raises(ValueError):
        quality_gate(val)


def test_quality_threshold_blocks(case):
    val = dict(case[2]);val["reconciliation"] = {"orders_total": 5, "orders_unmatched_customers": 1}
    assert quality_gate(val, max_unmatched_rate=.1)["flags"] == ["UNMATCHED_ORDER_RATE_EXCEEDED"]


def test_quality_empty_observations_block(case):
    val = dict(case[2]);val["reconciliation"] = {"orders_total": 0, "orders_unmatched_customers": 0}
    assert quality_gate(val)["status"] == "BLOCK"


def test_source_age_without_evidence_blocks(case):
    report = quality_gate(case[2], as_of_utc="2026-10-23T12:00:00Z", max_age_hours=24)
    assert "MISSING_SOURCE_FRESHNESS_EVIDENCE" in report["flags"]


def test_quality_stale_source_block(case):
    val = dict(case[2]);val["latest_source_timestamp_utc"] = "2026-10-20T12:00:00Z"
    result = quality_gate(val, as_of_utc="2026-10-22T12:00:00Z", max_age_hours=24)
    assert "SOURCE_STALE" in result["flags"]


def test_quality_future_timestamp_block(case):
    val = dict(case[2]);val["latest_source_timestamp_utc"] = "2026-10-24T12:00:00Z"
    result = quality_gate(val, as_of_utc="2026-10-22T12:00:00Z", max_age_hours=24)
    assert "SOURCE_TIMESTAMP_IN_FUTURE" in result["flags"]


@pytest.mark.parametrize("limit", [-1, True, 1.1, "1", float("nan"), float("inf")])
def test_quality_bad_limit_block(case, limit):
    with pytest.raises(ValueError):
        quality_gate(case[2], max_unmatched_rate=limit)


def test_quality_explicit_asof_required(case):
    with pytest.raises(ValueError, match="as_of_utc"):
        quality_gate(case[2], max_age_hours=24)


def test_failed_write_not_committed_and_can_retry(tmp_path, monkeypatch, fake_spark):
    from enterprise_automation.pipelines import spark_transform
    stamp = "2026-10-20T12:00:00Z"
    ingest_sources(sources=[
        Source("ERP", "simulated_api", [{"order_id": "O1", "customer_id": "C1", "amount_usd": "1.00", "updated_at_utc": stamp}]),
        Source("CRM", "simulated_api", [{"customer_id": "C1", "customer_name": "X", "updated_at_utc": stamp}]),
        Source("TICKETING", "csv_file_drop", []),
    ], root=tmp_path, run_id="s1", ingested_at_utc=stamp)
    original_write = spark_transform.write_enriched_parquet

    def fail(*args, **kwargs):
        Path(args[2]).mkdir(parents=True)
        raise RuntimeError("injected write failure")

    monkeypatch.setattr(spark_transform, "write_enriched_parquet", fail)
    with pytest.raises(RuntimeError, match="injected"):
        execute_cp2(root=tmp_path, source_run_id="s1", run_id="r1", spark=fake_spark)
    assert recovery_status(tmp_path, "r1").status == "RETRY_WITH_SAME_INPUT"
    monkeypatch.setattr(spark_transform, "write_enriched_parquet", original_write)
    new_run = execute_cp2(root=tmp_path, source_run_id="s1", run_id="r1", spark=fake_spark)
    assert new_run["replay_status"] == "processed"
    assert inspect_committed_run(tmp_path, "r1")["status"] == "PASS"
    assert execute_cp2(root=tmp_path, source_run_id="s1", run_id="r1", spark=fake_spark)["replay_status"] == "duplicate_skipped"


@pytest.mark.parametrize("limit", [float("nan"), float("inf")])
def test_quality_bad_age_limit_block(case, limit):
    with pytest.raises(ValueError):
        quality_gate(case[2], as_of_utc="2026-10-23T12:00:00Z", max_age_hours=limit)


def test_raw_symlink_blocked(case):
    root, _, _ = case
    raw = root / "data" / "raw" / "s1" / "erp.jsonl"
    other = raw.with_suffix(".copy")
    raw.rename(other)
    try:
        raw.symlink_to(other)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink permission unavailable")
    with pytest.raises(ValueError, match="Symlink"):
        inspect_committed_run(root, "r1")
