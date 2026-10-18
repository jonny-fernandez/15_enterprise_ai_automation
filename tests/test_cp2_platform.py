"""CP2 deterministic unit tests, with explicit optional real-Spark integration."""
import json
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.util

import pytest
from fastapi.testclient import TestClient
from enterprise_automation.adapters.synthetic import build_demo_sources
from enterprise_automation.api.main import app
from enterprise_automation.pipelines.ingestion import ingest_sources, canonical_json, sha256_text
from enterprise_automation.pipelines.cp2_pipeline import (
    _read_cp1, _enrich, _incremental, execute_cp2,
)
from enterprise_automation.warehouse.sqlite import SQLiteWarehouse

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"


@pytest.fixture
def cp1_run(tmp_path):
    ingest_sources(sources=build_demo_sources(FIXTURES), root=tmp_path,
                   run_id="source", ingested_at_utc="2026-10-16T00:00:00Z")
    return tmp_path


class FakeSparkReader:
    def __init__(self, spark):
        self.spark = spark
    def parquet(self, _):
        return self
    def count(self):
        return self.spark.count


class FakeSpark:
    def __init__(self):
        self.count = -1
        self.read = FakeSparkReader(self)


@pytest.fixture
def fake_spark(monkeypatch):
    import enterprise_automation.pipelines.spark_transform as trans
    spark = FakeSpark()
    def writer(_session, rows, path):
        Path(path).mkdir(parents=True)
        (Path(path) / "synthetic_test_only.parquet").write_text(str(len(rows)))
        spark.count = len(rows)
        return len(rows)
    monkeypatch.setattr(trans, "write_enriched_parquet", writer)
    monkeypatch.setattr(trans, "spark_joined_records", lambda _spark, sources: _enrich(sources)[0])
    return spark


def test_cp1_manifest_verified(cp1_run):
    manifest, rows, raw_hash = _read_cp1(cp1_run, "source")
    assert len(rows["ERP"]) == 3 and len(rows["CRM"]) == 3
    assert sum(len(x) for x in rows.values()) == 8
    assert len(raw_hash) == 64


def test_contract_tampering_rejected_even_with_recomputed_file_hash(cp1_run):
    path = cp1_run / "data/raw/source/erp.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    rows[0]["payload"]["amount_usd"] = -200
    rows[0]["record_sha256"] = sha256_text(canonical_json(rows[0]["payload"]))
    new_content = "".join(canonical_json(r) + "\n" for r in rows).encode()
    path.write_bytes(new_content)
    manifest_path = cp1_run / "artifacts/source_cp1_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sources"][0]["raw_sha256"] = hashlib.sha256(new_content).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="contract or provenance"):
        _read_cp1(cp1_run, "source")


def test_input_hash_mismatch_rejected(cp1_run):
    path = cp1_run / "data/raw/source/crm.jsonl"
    path.write_bytes(path.read_bytes() + b"junk")
    with pytest.raises(ValueError, match="hash mismatch"):
        _read_cp1(cp1_run, "source")


def test_path_traversal_rejected(cp1_run):
    with pytest.raises(ValueError, match="Invalid"):
        _read_cp1(cp1_run, "../source")


def test_manifest_path_injection_rejected(cp1_run):
    path = cp1_run / "artifacts/source_cp1_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["sources"][0]["raw_path"] = "../../../../tmp/unsafe"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Raw file path"):
        _read_cp1(cp1_run, "source")


def test_reconciliation_counts_and_provenance(cp1_run):
    _, rows, _ = _read_cp1(cp1_run, "source")
    output, quality = _enrich(rows)
    assert len(output) == 3
    assert quality == {"orders_total":3, "orders_unmatched_customers":0,
                       "tickets_unmatched_customers":0,"orders_matched_customers":3,
                       "tickets_total":2}
    assert [r["ticket_count"] for r in output] == [1,0,1]
    assert all(len(r["source_sha256"]) == 64 for r in output)


def test_unmatched_foreign_keys_preserved(cp1_run):
    _, rows, _ = _read_cp1(cp1_run, "source")
    rows["ERP"][0]["payload"]["customer_id"] = "C-NO-MATCH"
    rows["TICKETING"][0]["payload"]["customer_id"] = "C-NO-MATCH"
    output, quality = _enrich(rows)
    assert quality["orders_unmatched_customers"] == 1
    assert quality["tickets_unmatched_customers"] == 1
    assert output[0]["reconciliation_status"] == "unmatched_customer"
    assert output[0]["customer_name"] is None


@pytest.mark.parametrize("bad", ["a"*65, "../../escape", "<html>", ""])
def test_bad_run_ids_rejected_before_writes(cp1_run, fake_spark, bad):
    with pytest.raises(ValueError):
        execute_cp2(root=cp1_run, source_run_id="source", run_id=bad, spark=fake_spark)
    assert not (cp1_run / "artifacts/cp2_local_warehouse.sqlite").exists()


@pytest.mark.parametrize("load_mode,trigger_mode,lookback", [
    ("unknown", "manual", 1), ("full", "nope", 1),
    ("incremental", "manual", -1), ("full", "manual", 31),
    ("full", "manual", 1.5),
])
def test_modes_and_lookback_rejected(cp1_run, fake_spark, load_mode, trigger_mode, lookback):
    with pytest.raises(ValueError):
        execute_cp2(root=cp1_run, source_run_id="source", run_id="r1",
                    load_mode=load_mode, trigger_mode=trigger_mode,
                    lookback_days=lookback, spark=fake_spark)


def test_incremental_selects_new_and_skips_known(cp1_run):
    _, rows, _ = _read_cp1(cp1_run, "source")
    selected, stats = _incremental(rows, set(), {}, "incremental", 1)
    assert all(len(selected[k]) == len(rows[k]) for k in rows)
    versions = {(k, r["record_id"], r["record_sha256"]) for k,v in rows.items() for r in v}
    selected, stats = _incremental(rows, versions, {}, "incremental", 1)
    assert sum(len(v) for v in selected.values()) == 0
    assert sum(x["already_processed"] for x in stats.values()) == 8


def test_late_beyond_lookback_flagged(cp1_run):
    _, rows, _ = _read_cp1(cp1_run, "source")
    selected, stats = _incremental(rows, set(),
        {"ERP": datetime(2026, 10, 20, tzinfo=timezone.utc)}, "incremental", 1)
    assert len(selected["ERP"]) == 0
    assert stats["ERP"]["outside_lookback"] == 3


def test_full_refresh_selects_all_even_known(cp1_run):
    _, rows, _ = _read_cp1(cp1_run, "source")
    versions = {(k, r["record_id"], r["record_sha256"]) for k,v in rows.items() for r in v}
    selected, _ = _incremental(rows, versions, {}, "full", 1)
    assert sum(len(x) for x in selected.values()) == 8


def test_local_pipeline_writes_and_warehouse_reconciles(cp1_run, fake_spark):
    result = execute_cp2(root=cp1_run, source_run_id="source", run_id="first", spark=fake_spark)
    assert result["replay_status"] == "processed"
    assert result["rows_written_parquet"] == result["rows_readback_parquet"] == 3
    assert result["reconciliation"]["orders_matched_customers"] == 3
    assert (cp1_run / result["parquet_path"]).exists()
    db = SQLiteWarehouse(cp1_run / "artifacts/cp2_local_warehouse.sqlite")
    assert db.order_count() == 3
    assert set(db.watermarks()) == {"ERP", "CRM", "TICKETING"}
    assert len(db.known_versions()) == 8
    db.close()


def test_exact_replay_skipped_and_reuses_manifest(cp1_run, fake_spark):
    a = execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)
    b = execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)
    assert b["replay_status"] == "duplicate_skipped"
    assert b["rows_written_parquet"] == a["rows_written_parquet"]


def test_unchanged_incremental_has_no_new_orders(cp1_run, fake_spark):
    execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)
    second = execute_cp2(root=cp1_run, source_run_id="source", run_id="two", spark=fake_spark)
    assert second["rows_written_parquet"] == 0
    assert second["selection"]["ERP"]["already_processed"] == 3
    db = SQLiteWarehouse(cp1_run / "artifacts/cp2_local_warehouse.sqlite")
    assert db.order_count() == 3
    db.close()


def test_repeat_run_id_with_new_mode_rejected(cp1_run, fake_spark):
    execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)
    with pytest.raises(ValueError, match="different inputs"):
        execute_cp2(root=cp1_run, source_run_id="source", run_id="one",
                    trigger_mode="event", spark=fake_spark)


def test_event_id_dedup_across_run_ids(cp1_run, fake_spark):
    execute_cp2(root=cp1_run, source_run_id="source", run_id="one",
                trigger_mode="event", trigger_id="evt-1", spark=fake_spark)
    with pytest.raises(ValueError, match="Trigger ID"):
        execute_cp2(root=cp1_run, source_run_id="source", run_id="two",
                    trigger_mode="event", trigger_id="evt-1", spark=fake_spark)


def test_missing_spark_fails_without_state_commit(cp1_run):
    with pytest.raises(RuntimeError, match="Spark session required"):
        execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=None)
    db = SQLiteWarehouse(cp1_run / "artifacts/cp2_local_warehouse.sqlite")
    assert db.existing_run("one") is None
    db.close()


def test_failed_parquet_write_never_marks_run(cp1_run, fake_spark, monkeypatch):
    import enterprise_automation.pipelines.spark_transform as trans
    def broken(*args):
        raise OSError("synthetic crash")
    monkeypatch.setattr(trans, "write_enriched_parquet", broken)
    with pytest.raises(OSError):
        execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)
    db = SQLiteWarehouse(cp1_run / "artifacts/cp2_local_warehouse.sqlite")
    assert db.existing_run("one") is None
    assert db.order_count() == 0
    db.close()


def test_cp2_api_fail_closed(monkeypatch):
    monkeypatch.delenv("PROJECT15_API_KEY", raising=False)
    assert TestClient(app).post("/cp2/run", json={"source_run_id":"a", "run_id":"b"}).status_code == 503


def test_cp2_api_denies_wrong_key(monkeypatch):
    monkeypatch.setenv("PROJECT15_API_KEY", "synthetic-only-xx")
    assert TestClient(app).post("/cp2/run", headers={"X-API-Key":"wrong"},
       json={"source_run_id":"a", "run_id":"b"}).status_code == 401


def test_cp2_event_requires_id(monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT15_API_KEY", "synthetic-only-xx")
    monkeypatch.setenv("PROJECT15_ROOT", str(tmp_path))
    assert TestClient(app).post("/cp2/event", headers={"X-API-Key":"synthetic-only-xx"},
       json={"source_run_id":"a", "run_id":"b"}).status_code == 422


@pytest.mark.skipif(importlib.util.find_spec("pyspark") is None, reason="real Spark optional until CP2 deps installed")
def test_real_spark_parquet_partition_and_readback(cp1_run):
    """This MUST execute on Windows after installing CP2 dependencies."""
    from enterprise_automation.cp2_demo import local_spark
    spark = local_spark()
    try:
        result = execute_cp2(root=cp1_run, source_run_id="source", run_id="spark",
                             load_mode="full", spark=spark)
        out = cp1_run / result["parquet_path"]
        assert any(x.name.startswith("event_date=") for x in out.iterdir())
        frame = spark.read.parquet(str(out))
        assert frame.count() == 3
        assert frame.select("amount_usd").schema[0].dataType.simpleString() == "decimal(18,2)"
    finally:
        spark.stop()


def test_replay_rejects_tampered_parquet(cp1_run, fake_spark):
    result = execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)
    part = cp1_run / "data/processed/one" / result["parquet_files"][0]["path"]
    part.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="has changed"):
        execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)

def test_replay_rejects_lost_manifest(cp1_run, fake_spark):
    execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)
    (cp1_run / "data/processed/one/cp2_manifest.json").unlink()
    with pytest.raises(FileNotFoundError, match="output missing"):
        execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)

def test_input_source_type_spoofing_rejected(cp1_run):
    p = cp1_run / "artifacts/source_cp1_manifest.json"
    man = json.loads(p.read_text())
    man["sources"][0]["source_type"] = "real_production_api"
    p.write_text(json.dumps(man))
    with pytest.raises(ValueError, match="source adapter"):
        _read_cp1(cp1_run, "source")


def test_replay_rejects_extra_parquet_file(cp1_run, fake_spark):
    result = execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)
    output_dir = cp1_run / "data/processed/one/parquet"
    (output_dir / "untracked.parquet").write_bytes(b"unexpected extra part")
    with pytest.raises(ValueError, match="inventory has changed"):
        execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)



def test_replay_rejects_windows_separator_in_manifest(cp1_run, fake_spark):
    # Corrupt both the audit database and the JSON manifest to reach the
    # portable path-validation check rather than the summary comparison.
    import sqlite3
    execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)
    database = cp1_run / "artifacts/cp2_local_warehouse.sqlite"
    with sqlite3.connect(database) as conn:
        old_summary = conn.execute("SELECT summary_json FROM runs WHERE run_id='one'").fetchone()[0]
        corrupted = json.loads(old_summary)
        corrupted["parquet_files"][0]["path"] = r"parquet\synthetic_test_only.parquet"
        conn.execute("UPDATE runs SET summary_json=? WHERE run_id='one'", (json.dumps(corrupted),))
    manifest = cp1_run / "data/processed/one/cp2_manifest.json"
    manifest.write_text(json.dumps(corrupted), encoding="utf-8")
    with pytest.raises(ValueError, match="missing or unsafe"):
        execute_cp2(root=cp1_run, source_run_id="source", run_id="one", spark=fake_spark)
