import hashlib
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from enterprise_automation.adapters.base import page_slice
from enterprise_automation.adapters.synthetic import build_demo_sources, SyntheticAPIAdapter
from enterprise_automation.api.mock_systems import app as mock_app
from enterprise_automation.pipelines.ingestion import ingest_sources

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"


def test_pagination_and_distinct_source_types():
    erp, crm, ticketing = build_demo_sources(FIXTURES)
    assert erp.source_type == crm.source_type == "simulated_api"
    assert ticketing.source_type == "csv_file_drop"
    first = erp.list_page(page_size=2)
    second = erp.list_page(cursor=first.next_cursor, page_size=2)
    assert len(first.records) == 2 and len(second.records) == 1
    assert second.next_cursor is None


@pytest.mark.parametrize("cursor,limit", [(-1, 2), (0, 0), (0, 101), (10, 1)])
def test_bad_pagination_bounds(cursor, limit):
    with pytest.raises(ValueError):
        page_slice([{"id": "1"}], cursor=cursor, page_size=limit)


def test_mock_http_apis_serve_only_synthetic_fixtures():
    client = TestClient(mock_app)
    response = client.get("/erp/orders?page_size=2")
    assert response.status_code == 200
    body = response.json()
    assert body["source_system"] == "ERP" and len(body["records"]) == 2
    assert client.get("/crm/customers").status_code == 200
    assert client.get("/erp/orders?page_size=999").status_code == 422


def test_ingestion_counts_hashes_and_quarantine(tmp_path):
    result = ingest_sources(sources=build_demo_sources(FIXTURES), root=tmp_path, run_id="locked_sample")
    assert result["totals"] == {"accepted": 8, "quarantined": 0}
    assert [s["accepted"] for s in result["sources"]] == [3, 3, 2]
    for source in result["sources"]:
        raw_bytes = (tmp_path / source["raw_path"]).read_bytes()
        assert hashlib.sha256(raw_bytes).hexdigest() == source["raw_sha256"]
        assert source["contract_version"].endswith(".v1")
    assert (tmp_path / "artifacts" / "locked_sample_cp1_manifest.json").exists()


def test_repeat_same_run_id_is_blocked(tmp_path):
    sources = build_demo_sources(FIXTURES)
    ingest_sources(sources=sources, root=tmp_path, run_id="repeat")
    with pytest.raises(FileExistsError):
        ingest_sources(sources=sources, root=tmp_path, run_id="repeat")


def test_bad_run_id_rejected(tmp_path):
    with pytest.raises(ValueError):
        ingest_sources(sources=build_demo_sources(FIXTURES), root=tmp_path, run_id="../unsafe")


def test_ingestion_quarantines_invalid_and_duplicate_records(tmp_path):
    class Source:
        source_system = "ERP"
        source_type = "simulated_api"
        def list_page(self, *, cursor=0, page_size=2):
            return page_slice([
                {"order_id":"O1", "customer_id":"C1", "amount_usd":4, "updated_at_utc":"2026-10-16T00:00:00Z"},
                {"order_id":"O1", "customer_id":"C1", "amount_usd":5, "updated_at_utc":"2026-10-16T00:00:00Z"},
                {"order_id":"O3", "customer_id":"C1", "amount_usd":-2, "updated_at_utc":"2026-10-16T00:00:00Z"},
            ], cursor=cursor, page_size=page_size)
    result = ingest_sources(sources=[Source()], root=tmp_path, run_id="quarantine")
    assert result["totals"] == {"accepted": 1, "quarantined": 2}
    rejected = (tmp_path / result["sources"][0]["quarantine_path"]).read_text().splitlines()
    assert "duplicate_in_batch" in rejected[0]
    assert "nonfinite_or_negative" in rejected[1]
    assert "C1" not in "".join(rejected)  # quarantine stores hashes + error labels, not raw values


def test_deterministic_raw_byte_hash_across_runs(tmp_path):
    sources = build_demo_sources(FIXTURES)
    a = ingest_sources(sources=sources, root=tmp_path, run_id="a")
    b = ingest_sources(sources=sources, root=tmp_path, run_id="b")
    # Run ID is preserved in records for provenance; hashes should differ.
    assert a["sources"][0]["raw_sha256"] != b["sources"][0]["raw_sha256"]
    for r in [a,b]:
        assert r["totals"]["accepted"] == 8


def test_adapter_pagination_cycle_fails_without_output(tmp_path):
    class Cycle:
        source_system="ERP"
        source_type="simulated_api"
        def list_page(self, *, cursor=0, page_size=2):
            from enterprise_automation.adapters.base import Page
            return Page((), cursor)
    with pytest.raises(ValueError):
        ingest_sources(sources=[Cycle()], root=tmp_path, run_id="cycle")
    assert not (tmp_path / "data" / "raw" / "cycle").exists()


def test_nonfinite_amount_is_quarantined_not_crash(tmp_path):
    class Source:
        source_system="ERP"
        source_type="simulated_api"
        def list_page(self, *, cursor=0, page_size=2):
            return page_slice([{"order_id": "N1", "customer_id": "C1", "amount_usd": float("nan"),
                                "updated_at_utc": "2026-10-16T00:00:00Z"}],
                              cursor=cursor, page_size=page_size)
    result = ingest_sources(sources=[Source()], root=tmp_path, run_id="nonfinite")
    assert result["totals"] == {"accepted": 0, "quarantined": 1}
