"""CP2 local synthetic data-platform orchestrator.

Inputs come ONLY from locally generated CP1 run manifests. Verifies all raw
file hashes, record hashes, schema contracts, record counts and source keys.
No live integrations. Writes partitioned Parquet and a local SQLite warehouse.
"""
import hashlib
import json
import re
import shutil
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

from enterprise_automation.contracts import CONTRACTS, validate_record
from enterprise_automation.pipelines.ingestion import canonical_json, sha256_text
from enterprise_automation.pipelines.incremental_load import parse_timestamp
from enterprise_automation.warehouse.sqlite import SQLiteWarehouse

SAFE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MODES = {"scheduled", "event", "api", "manual"}


def _safe_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not SAFE.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    return value


def _read_cp1(root: Path, source_run_id: str) -> tuple[dict, dict[str, list[dict]], str]:
    _safe_id(source_run_id, "source_run_id")
    path = root / "artifacts" / f"{source_run_id}_cp1_manifest.json"
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if (manifest.get("schema_version") != "cp1.manifest.v1" or
            manifest.get("run_id") != source_run_id or
            manifest.get("execution_mode") != "offline_synthetic"):
        raise ValueError("Unexpected or non-synthetic source manifest")
    items = manifest.get("sources")
    if not isinstance(items, list) or len(items) != len(CONTRACTS):
        raise ValueError("Missing or repeated source systems")
    by_source = {}
    totals = {"accepted": 0, "quarantined": 0}
    for source in items:
        name = source.get("source_system")
        if name not in CONTRACTS or name in by_source:
            raise ValueError("Invalid source list")
        contract = CONTRACTS[name]
        expected_type = "csv_file_drop" if name == "TICKETING" else "simulated_api"
        if source.get("source_type") != expected_type:
            raise ValueError("Unexpected source adapter type")
        raw_rel = f"data/raw/{source_run_id}/{name.lower()}.jsonl"
        quarantine_rel = f"data/raw/{source_run_id}/{name.lower()}_quarantine.jsonl"
        if (source.get("raw_path") != raw_rel or source.get("quarantine_path") != quarantine_rel
                or source.get("contract_version") != contract.version):
            raise ValueError("Raw file path or contract version mismatch")
        records = []
        for label, rel in (("raw", raw_rel), ("quarantine", quarantine_rel)):
            content = (root / rel).read_bytes()
            if hashlib.sha256(content).hexdigest() != source.get(label + "_sha256"):
                raise ValueError(f"Input hash mismatch for {name}/{label}")
            lines = content.splitlines()
            expected = source.get("accepted" if label == "raw" else "quarantined")
            if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0 or len(lines) != expected:
                raise ValueError("Manifest row count mismatch")
            if label == "raw":
                seen_keys = set()
                for line in lines:
                    wrapper = json.loads(line)
                    row = wrapper.get("payload")
                    if (wrapper.get("source_system") != name or wrapper.get("record_id") in seen_keys
                            or wrapper.get("contract_version") != contract.version
                            or wrapper.get("source_type") != expected_type
                            or wrapper.get("run_id") != source_run_id
                            or not isinstance(row, dict)
                            or wrapper.get("record_id") != row.get(contract.key_field)
                            or wrapper.get("record_sha256") != sha256_text(canonical_json(row))
                            or validate_record(row, contract)):
                        raise ValueError("Raw record contract or provenance mismatch")
                    seen_keys.add(wrapper["record_id"])
                    records.append(wrapper)
        by_source[name] = records
        totals["accepted"] += source["accepted"]
        totals["quarantined"] += source["quarantined"]
    if totals != manifest.get("totals"):
        raise ValueError("Source totals disagree with manifest")
    return manifest, by_source, hashlib.sha256(raw).hexdigest()


def _enrich(source_records: dict[str, list[dict]]) -> tuple[list[dict], dict]:
    """Conservative join on explicitly shared customer_id; preserve orphans."""
    customers = {r["payload"]["customer_id"]: r["payload"] for r in source_records["CRM"]}
    ticket_count = {}
    orphan_tickets = 0
    for wrapper in source_records["TICKETING"]:
        cid = wrapper["payload"]["customer_id"]
        ticket_count[cid] = ticket_count.get(cid, 0) + 1
        if cid not in customers:
            orphan_tickets += 1
    result = []
    unmatched_orders = 0
    for wrapper in sorted(source_records["ERP"], key=lambda r: r["record_id"]):
        order = wrapper["payload"]
        customer = customers.get(order["customer_id"])
        if customer is None:
            unmatched_orders += 1
        try:
            amount = Decimal(str(order["amount_usd"]))
            if not amount.is_finite() or abs(amount) >= Decimal("1e16") or amount != amount.quantize(Decimal("0.01")):
                raise ValueError("Invalid cent precision/amount range")
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Unrepresentable financial amount") from exc
        updated = parse_timestamp(order["updated_at_utc"], require_timezone=True)
        result.append({
            "order_id": order["order_id"],
            "customer_id": order["customer_id"],
            "customer_name": customer["customer_name"] if customer else None,
            "amount_usd": str(amount.quantize(Decimal("0.01"))),
            "updated_at_utc": updated.isoformat(),
            "ticket_count": ticket_count.get(order["customer_id"], 0),
            "reconciliation_status": "matched" if customer else "unmatched_customer",
            "source_sha256": wrapper["record_sha256"],
            "event_date": updated.date().isoformat(),
        })
    quality = {"orders_total": len(result), "orders_unmatched_customers": unmatched_orders,
               "tickets_unmatched_customers": orphan_tickets,
               "orders_matched_customers": len(result) - unmatched_orders,
               "tickets_total": len(source_records["TICKETING"])}
    return result, quality


def _incremental(records: dict[str, list[dict]], existing_versions, marks, mode, lookback_days):
    selected = {}
    counts = {}
    for source, wrappers in records.items():
        selected[source] = []
        skipped = late = 0
        watermark = marks.get(source)
        for r in wrappers:
            key = (source, r["record_id"], r["record_sha256"])
            timestamp = parse_timestamp(r["payload"]["updated_at_utc"], require_timezone=True)
            if mode == "full":
                selected[source].append(r)
            elif key in existing_versions:
                skipped += 1
            elif watermark and timestamp < watermark - timedelta(days=lookback_days):
                late += 1
            else:
                selected[source].append(r)
        counts[source] = {"selected": len(selected[source]), "already_processed": skipped,
                          "outside_lookback": late}
    return selected, counts


def execute_cp2(*, root: Path, source_run_id: str, run_id: str,
                trigger_mode: str = "manual", trigger_id: str | None = None,
                load_mode: str = "incremental", lookback_days: int = 1,
                spark=None) -> dict:
    """Run synthetic transformations with per-run replay protection.

    Spark session supplied by caller. This function doesn't auto-install Java
    or connect to anything external. A failed run never updates the warehouse.
    """
    from enterprise_automation.pipelines.spark_transform import write_enriched_parquet, spark_joined_records

    _safe_id(run_id, "run_id")
    _safe_id(source_run_id, "source_run_id")
    if trigger_mode not in MODES or load_mode not in {"full", "incremental"}:
        raise ValueError("Unsupported trigger/load mode")
    trigger_id = _safe_id(trigger_id or run_id, "trigger_id")
    if type(lookback_days) is not int or not 0 <= lookback_days <= 30:
        raise ValueError("lookback_days must be integer in 0..30")
    root = Path(root).resolve()
    _, records, input_hash = _read_cp1(root, source_run_id)
    signature = sha256_text(canonical_json({"source_run_id": source_run_id, "input_hash": input_hash,
            "mode": trigger_mode, "trigger_id": trigger_id, "load_mode": load_mode,
            "lookback_days": lookback_days}))
    warehouse = SQLiteWarehouse(root / "artifacts" / "cp2_local_warehouse.sqlite")
    out_dir = root / "data" / "processed" / run_id
    try:
        existing = warehouse.existing_run(run_id)
        if existing:
            if existing["signature"] != signature:
                raise ValueError("Run ID was already committed with different inputs")
            if not (out_dir / "cp2_manifest.json").is_file() or not (out_dir / "parquet").is_dir():
                raise FileNotFoundError("Committed run output missing: manual recovery required")
            answer = json.loads(existing["summary_json"])
            if json.loads((out_dir / "cp2_manifest.json").read_text(encoding="utf-8")) != answer:
                raise ValueError("Committed run manifest has changed")
            recorded_paths = set()
            for part in answer["parquet_files"]:
                # Manifest paths use forward slashes on every OS.  Never compare
                # str(Path(...)) with "parquet/": Windows converts it to '\\'.
                relative = part["path"]
                if not isinstance(relative, str) or "\\" in relative or ":" in relative:
                    raise ValueError("Committed Parquet part is missing or unsafe")
                posix = PurePosixPath(relative)
                components = relative.split("/")
                if (len(components) < 2 or components[0] != "parquet"
                        or any(c in {"", ".", ".."} for c in components)
                        or posix.is_absolute() or not relative.endswith(".parquet")
                        or relative in recorded_paths):
                    raise ValueError("Committed Parquet part is missing or unsafe")
                recorded_paths.add(relative)
                part_path = out_dir.joinpath(*components)
                if (not part_path.is_file() or part_path.is_symlink()
                        or not part_path.resolve().is_relative_to(out_dir.resolve())):
                    raise ValueError("Committed Parquet part is missing or unsafe")
                expected = part["sha256"]
                if hashlib.sha256(part_path.read_bytes()).hexdigest() != expected:
                    raise ValueError("Committed Parquet part has changed")
            # Detect inserted files in addition to deleted or modified files.
            actual_paths = {p.relative_to(out_dir).as_posix()
                            for p in (out_dir / "parquet").rglob("*.parquet") if p.is_file()}
            if actual_paths != recorded_paths:
                raise ValueError("Committed Parquet file inventory has changed")
            return {**answer, "replay_status": "duplicate_skipped"}
        previous_trigger = warehouse.existing_trigger(trigger_mode, trigger_id)
        if previous_trigger:
            raise ValueError("Trigger ID already consumed by a different run")
        selected, selection_stats = _incremental(records, warehouse.known_versions(), warehouse.watermarks(),
                                                   load_mode, lookback_days)
        full_enriched, quality = _enrich(records)
        current_keys = {r["record_id"] for r in selected["ERP"]}
        enriched = [r for r in full_enriched if r["order_id"] in current_keys]
        if spark is None:
            raise RuntimeError("CP2 Spark session required; no silent alternate engine")
        spark_enriched = spark_joined_records(spark, records)
        if spark_enriched != full_enriched:
            raise ValueError("Spark join results disagree with independent reference")
        if out_dir.exists():
            # Local, uncommitted output from interrupted run; safe to rebuild.
            # Refuse unexpected files or symlinks rather than deleting arbitrary data.
            allowed = {"parquet", "cp2_manifest.json"}
            if out_dir.is_symlink() or any(x.name not in allowed or x.is_symlink() for x in out_dir.iterdir()):
                raise FileExistsError("Unexpected uncommitted output; manual review required")
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=False)
        parquet = out_dir / "parquet"
        try:
            written = write_enriched_parquet(spark, enriched, str(parquet))
            if written != len(enriched):
                raise ValueError("Spark write count does not reconcile")
            verify_count = spark.read.parquet(str(parquet)).count()
            if verify_count != written:
                raise ValueError("Parquet readback count does not reconcile")
            parquet_files = sorted(p for p in parquet.rglob("*.parquet") if p.is_file())
            if not parquet_files:
                raise ValueError("No Spark Parquet output files found")
            part_hashes = [{"path": p.relative_to(out_dir).as_posix(),
                            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                            "bytes": p.stat().st_size} for p in parquet_files]
            summary = {
                "schema_version": "cp2.manifest.v1", "run_id": run_id,
                "source_run_id": source_run_id, "source_manifest_sha256": input_hash,
                "execution_mode": "offline_synthetic", "trigger_mode": trigger_mode,
                "trigger_id": trigger_id, "load_mode": load_mode,
                "selection": selection_stats, "reconciliation": quality,
                "rows_written_parquet": written, "rows_readback_parquet": verify_count,
                "rows_selected_erp": len(enriched),
                "spark_join_verified": True,
                "parquet_files": part_hashes,
                "parquet_path": f"data/processed/{run_id}/parquet",
                "warehouse": "local_sqlite", "lookback_days": lookback_days,
                "source_versions": {key: len(value) for key, value in selected.items()},
                "limitations": ["local synthetic only", "not live PostgreSQL", "not Azure",
                    "CRM/ticket updates do not automatically rebuild unchanged ERP orders",
                    "single-process SQLite does not provide distributed worker locking"],
            }
            (out_dir / "cp2_manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                                      encoding="utf-8")
            warehouse.commit_run(run_id=run_id, signature=signature, source_run_id=source_run_id,
                trigger_mode=trigger_mode, trigger_id=trigger_id, summary=summary,
                selected_records=selected, rows=enriched)
        except BaseException:
            # Output is not a committed result. Next run can repair safely.
            raise
        return {**summary, "replay_status": "processed"}
    finally:
        warehouse.close()
