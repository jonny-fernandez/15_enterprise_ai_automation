"""CP1 raw landing: validated records, quarantine, SHA256 hashes and manifests.

Only works on explicit synthetic/mocked source adapters. No production systems.
"""
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from enterprise_automation.contracts import CONTRACTS, validate_record
from enterprise_automation.pipelines.incremental_load import parse_timestamp


@dataclass(frozen=True)
class IngestedRecord:
    source_system: str
    record_id: str
    payload: dict
    ingested_at_utc: str
    contract_version: str = ""
    record_sha256: str = ""
    run_id: str = ""


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_jsonl(destination: Path, rows: list[dict]) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    contents = "".join(canonical_json(row) + "\n" for row in rows)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(contents.encode("utf-8"))
    os.replace(temporary, destination)
    return hashlib.sha256(contents.encode("utf-8")).hexdigest()


def ingest_sources(*, sources, root: Path, run_id: str,
                   ingested_at_utc: str | None = None, page_size: int = 2) -> dict:
    """Ingest synthetic sources with per-run quarantine; no external writes."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        raise ValueError("run_id must contain only letters, digits, _ or -")
    if ingested_at_utc is None:
        ingested_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    parse_timestamp(ingested_at_utc, require_timezone=True)
    root = Path(root)
    run_dir = root / "data" / "raw" / run_id
    manifest_path = root / "artifacts" / f"{run_id}_cp1_manifest.json"
    if run_dir.exists() or manifest_path.exists():
        raise FileExistsError("Run ID already exists; choose a new run ID (no silent overwrite)")
    # All in-memory validation precedes any writes.
    staged = []
    seen_sources: set[str] = set()
    for adapter in sources:
        source = adapter.source_system
        if source not in CONTRACTS or source in seen_sources:
            raise ValueError("Unknown or duplicate source contract")
        seen_sources.add(source)
        contract = CONTRACTS[source]
        accepted, rejected = [], []
        seen_ids: set[str] = set()
        cursor = 0
        visited_cursors = set()
        while True:
            if cursor in visited_cursors:
                raise ValueError("Adapter pagination cycle detected")
            visited_cursors.add(cursor)
            page = adapter.list_page(cursor=cursor, page_size=page_size)
            for record in page.records:
                errors = validate_record(record, contract)
                key = record.get(contract.key_field) if isinstance(record, dict) else None
                if isinstance(key, str) and key in seen_ids:
                    errors.append(f"{contract.key_field}:duplicate_in_batch")
                if errors:
                    rejected.append({"source": source, "errors": sorted(set(errors)),
                                     "input_sha256": sha256_text(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=True))})
                    continue
                seen_ids.add(key)
                accepted.append({"source_system": source, "source_type": adapter.source_type,
                                 "contract_version": contract.version, "record_id": key,
                                 "payload": record, "record_sha256": sha256_text(canonical_json(record)),
                                 "ingested_at_utc": ingested_at_utc, "run_id": run_id})
            if page.next_cursor is None:
                break
            if not isinstance(page.next_cursor, int) or page.next_cursor <= cursor:
                raise ValueError("Adapter cursor must advance")
            cursor = page.next_cursor
        staged.append((source, contract.version, adapter.source_type, accepted, rejected))
    manifest = {"schema_version": "cp1.manifest.v1", "run_id": run_id,
                "execution_mode": "offline_synthetic", "sources": [],
                "totals": {"accepted": 0, "quarantined": 0}}
    for source, version, source_type, accepted, rejected in staged:
        source_filename = f"{source.lower()}.jsonl"
        quarantine_filename = f"{source.lower()}_quarantine.jsonl"
        raw_hash = _atomic_jsonl(run_dir / source_filename, accepted)
        quarantine_hash = _atomic_jsonl(run_dir / quarantine_filename, rejected)
        manifest["sources"].append({"source_system": source, "source_type": source_type,
            "contract_version": version, "accepted": len(accepted), "quarantined": len(rejected),
            "raw_path": f"data/raw/{run_id}/{source_filename}", "raw_sha256": raw_hash,
            "quarantine_path": f"data/raw/{run_id}/{quarantine_filename}",
            "quarantine_sha256": quarantine_hash})
        manifest["totals"]["accepted"] += len(accepted)
        manifest["totals"]["quarantined"] += len(rejected)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
