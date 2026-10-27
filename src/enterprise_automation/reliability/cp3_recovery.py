"""Read-only verification and recovery classification for local synthetic CP2 runs.

No replays are executed or data deleted by this module. A recovery plan is
advice, not an action. Explicit CP2 calls remain the only mutation path.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sqlite3
from urllib.parse import quote

from enterprise_automation.pipelines.cp2_pipeline import _read_cp1
from enterprise_automation.pipelines.incremental_load import parse_timestamp

_RUN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class RecoveryCheck:
    status: str
    reason: str
    run_id: str
    committed: bool


def _id(value: str) -> str:
    if not isinstance(value, str) or not _RUN.fullmatch(value):
        raise ValueError("Invalid run identifier")
    return value


def _regular_file(base: Path, target: Path) -> Path:
    """Forbid symlinks in every component from trusted root to target."""
    base = Path(base).resolve(strict=True)
    relative = target.relative_to(base)  # must be constructed from validated parts
    current = base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink in evidence path")
    if not current.is_file():
        raise ValueError("Evidence file missing")
    return current


def _read_json(root: Path, path: Path) -> dict:
    obj = json.loads(_regular_file(root, path).read_bytes())
    if not isinstance(obj, dict):
        raise ValueError("Expected JSON object")
    return obj


def _connect_readonly(path: Path):
    if not path.is_file() or path.is_symlink():
        raise ValueError("Warehouse database missing or symlinked")
    connection = sqlite3.connect("file:" + quote(str(path.resolve()), safe="/:\\") + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def recovery_status(root: Path, run_id: str) -> RecoveryCheck:
    """Classify safe next actions; never delete or repair on its own."""
    root = Path(root).resolve()
    run_id = _id(run_id)
    out = root / "data" / "processed" / run_id
    warehouse_path = root / "artifacts" / "cp2_local_warehouse.sqlite"
    if not warehouse_path.exists():
        return RecoveryCheck("NEW", "No warehouse: normal first run only", run_id, False)
    with closing(_connect_readonly(warehouse_path)) as db:
        recorded = db.execute("SELECT run_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if recorded:
        return RecoveryCheck("COMMITTED_VERIFY", "Verify hashes; do not replace committed output", run_id, True)
    if out.is_symlink():
        return RecoveryCheck("MANUAL_REVIEW", "Uncommitted output is a symlink", run_id, False)
    if out.exists():
        if not out.is_dir() or any(p.is_symlink() or p.name not in {"parquet", "cp2_manifest.json"}
                                   for p in out.iterdir()):
            return RecoveryCheck("MANUAL_REVIEW", "Uncommitted output contains unexpected files", run_id, False)
        return RecoveryCheck("RETRY_WITH_SAME_INPUT", "CP2 owns deletion of uncommitted output", run_id, False)
    return RecoveryCheck("NEW", "No prior output for this run", run_id, False)


def inspect_committed_run(root: Path, run_id: str, *, verify_source: bool = True) -> dict:
    """Fail closed on source, SQL summary, manifest or Parquet evidence mismatch.

    Not a transaction replayer: never calls Spark or performs any writes.
    """
    root = Path(root).resolve()
    run_id = _id(run_id)
    status = recovery_status(root, run_id)
    if not status.committed:
        raise ValueError("Run is not committed; inspect recovery status first")
    out = root / "data" / "processed" / run_id
    if out.is_symlink() or (out / "parquet").is_symlink():
        raise ValueError("Symlinked run output")
    manifest_path = out / "cp2_manifest.json"
    manifest = _read_json(root, manifest_path)
    if manifest.get("schema_version") != "cp2.manifest.v1" or manifest.get("run_id") != run_id:
        raise ValueError("Manifest contract or identity mismatch")
    if manifest.get("execution_mode") != "offline_synthetic" or manifest.get("warehouse") != "local_sqlite":
        raise ValueError("Unexpected execution mode or warehouse")
    source_id = _id(manifest.get("source_run_id"))
    with closing(_connect_readonly(root / "artifacts" / "cp2_local_warehouse.sqlite")) as db:
        row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None or row["source_run_id"] != source_id:
        raise ValueError("Warehouse run identity mismatch")
    if json.loads(row["summary_json"]) != manifest:
        raise ValueError("Warehouse and disk manifests differ")
    if row["trigger_mode"] != manifest["trigger_mode"] or row["trigger_id"] != manifest["trigger_id"]:
        raise ValueError("Warehouse and disk triggers differ")
    if verify_source:
        # Also reject symlink indirection even when the target bytes match.
        _regular_file(root, root / "artifacts" / f"{source_id}_cp1_manifest.json")
        for system in ("erp", "crm", "ticketing"):
            for suffix in ("", "_quarantine"):
                _regular_file(root, root / "data" / "raw" / source_id / f"{system}{suffix}.jsonl")
        # Validates every raw input hash, record payload and source contract.
        _, _, source_sha = _read_cp1(root, source_id)
        if source_sha != manifest["source_manifest_sha256"]:
            raise ValueError("Source manifest hash mismatch")
    rows = manifest.get("rows_written_parquet")
    if type(rows) is not int or rows < 0 or rows != manifest.get("rows_readback_parquet") or rows != manifest.get("rows_selected_erp"):
        raise ValueError("Parquet/readback/selected record counts disagree")
    if manifest.get("parquet_path") != f"data/processed/{run_id}/parquet":
        raise ValueError("Unexpected Parquet location")
    parts = manifest.get("parquet_files")
    if not isinstance(parts, list) or not parts:
        raise ValueError("Parquet manifest inventory missing")
    expected = set()
    digest_parts = []
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError("Malformed Parquet part")
        rel = part.get("path")
        if (not isinstance(rel, str) or "\\" in rel or ":" in rel
                or not rel.startswith("parquet/") or not rel.endswith(".parquet")
                or any(x in ("", ".", "..") for x in rel.split("/"))
                or PurePosixPath(rel).is_absolute() or rel in expected):
            raise ValueError("Invalid or repeated Parquet part path")
        expected.add(rel)
        actual_path = _regular_file(root, out.joinpath(*rel.split("/")))
        content = actual_path.read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        if part.get("sha256") != actual or part.get("bytes") != len(content):
            raise ValueError("Parquet digest or size mismatch")
        digest_parts.append({"path": rel, "sha256": actual, "bytes": len(content)})
    actual = set()
    for path in (out / "parquet").rglob("*"):
        if path.is_symlink():
            raise ValueError("Unexpected symlink in Parquet tree")
        if path.is_file() and path.suffix == ".parquet":
            actual.add(path.relative_to(out).as_posix())
    if actual != expected:
        raise ValueError("Missing or unlisted Parquet files")
    # Canonical digest is stable even when JSON whitespace differs, but the
    # original on-disk bytes are hashed independently for tamper evidence.
    original_hash = hashlib.sha256(_regular_file(root, manifest_path).read_bytes()).hexdigest()
    return {"run_id": run_id, "source_run_id": source_id, "status": "PASS",
            "manifest_sha256": original_hash, "source_manifest_sha256": manifest["source_manifest_sha256"],
            "parquet_files": sorted(digest_parts, key=lambda row: row["path"]),
            "parquet_rows": rows, "input_verification": "full" if verify_source else "not_checked",
            "limitations": ["offline synthetic local only", "read-only inspection", "does not prove Spark throughput", "historical warehouse orders may be superseded by later incremental runs"]}


def quality_gate(manifest: dict, *, max_unmatched_rate: float = .05, as_of_utc: str | None = None,
                 max_age_hours: float | None = None) -> dict:
    """A deterministic monitoring gate; missing required observations block."""
    if isinstance(max_unmatched_rate, bool) or not isinstance(max_unmatched_rate, (int, float)) or not math.isfinite(max_unmatched_rate) or not 0 <= max_unmatched_rate <= 1:
        raise ValueError("Invalid unmatched-rate limit")
    quality = manifest.get("reconciliation")
    if not isinstance(quality, dict):
        raise ValueError("Missing reconciliation metrics")
    count, unmatched = quality.get("orders_total"), quality.get("orders_unmatched_customers")
    if (type(count) is not int or type(unmatched) is not int or count < 0
            or unmatched < 0 or unmatched > count):
        raise ValueError("Malformed order quality counts")
    flags = []
    if count == 0:
        flags.append("NO_ORDERS_TO_EVALUATE")
    elif unmatched / count > max_unmatched_rate:
        flags.append("UNMATCHED_ORDER_RATE_EXCEEDED")
    if max_age_hours is not None:
        if isinstance(max_age_hours, bool) or not isinstance(max_age_hours, (float, int)) or not math.isfinite(max_age_hours) or max_age_hours <= 0:
            raise ValueError("Invalid staleness bound")
        if as_of_utc is None:
            raise ValueError("Explicit as_of_utc required; no inferred clock")
        reference = parse_timestamp(as_of_utc, require_timezone=True)
        latest = manifest.get("latest_source_timestamp_utc")
        if latest is None:
            flags.append("MISSING_SOURCE_FRESHNESS_EVIDENCE")
        else:
            observation = parse_timestamp(latest, require_timezone=True)
            lag = (reference - observation).total_seconds() / 3600
            if lag < 0:
                flags.append("SOURCE_TIMESTAMP_IN_FUTURE")
            elif lag > max_age_hours:
                flags.append("SOURCE_STALE")
    return {"status": "PASS" if not flags else "BLOCK", "flags": flags,
            "orders": count, "unmatched_orders": unmatched,
            "unmatched_rate": unmatched / count if count else None}


def check_repeatability(root: Path, run_id: str) -> dict:
    """Read-only two-pass hash verification; does not execute a pipeline replay."""
    first = inspect_committed_run(root, run_id)
    second = inspect_committed_run(root, run_id)
    if first != second:
        raise ValueError("Non-deterministic integrity snapshot")
    return {"status": "PASS", "identical_readonly_checks": True,
            "run_id": run_id, "manifest_sha256": first["manifest_sha256"],
            "note": "Does not verify idempotent execution; duplicate-run tests remain separate"}
