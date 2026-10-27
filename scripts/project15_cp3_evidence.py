"""Read-only local CP3 evidence report. No Spark session or external integrations."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from enterprise_automation.reliability.cp3_recovery import (
    inspect_committed_run, quality_gate, check_repeatability, recovery_status,
)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    db_path = root / "artifacts" / "cp2_local_warehouse.sqlite"
    outputs = []
    if db_path.exists():
        if db_path.is_symlink():
            raise ValueError("Refusing symlinked warehouse")
        from urllib.parse import quote
        uri = "file:" + quote(str(db_path.resolve()), safe="/:\\") + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            ids = [r[0] for r in db.execute("SELECT run_id FROM runs ORDER BY run_id")]
        for run_id in ids:
            try:
                detail = inspect_committed_run(root, run_id)
                manifest = json.loads((root / "data" / "processed" / run_id / "cp2_manifest.json").read_text())
                health = quality_gate(manifest)
                repeat = check_repeatability(root, run_id)
                outputs.append({"run_id": run_id, "integrity": detail,
                                "quality": health, "repeatability": repeat})
            except (OSError, ValueError, sqlite3.Error, KeyError, json.JSONDecodeError) as exc:
                outputs.append({"run_id": run_id, "status": "BLOCK", "reason": type(exc).__name__ + ": " + str(exc)})
    total = len(outputs)
    failures = sum(1 for record in outputs if record.get("status") == "BLOCK" or record.get("quality",{}).get("status") == "BLOCK")
    summary = {
        "schema_version": "project15.cp3.local-inspection.v1",
        "status": "PASS" if total and not failures else "NOT_VERIFIED" if not total else "BLOCK",
        "committed_runs_inspected": total,
        "failures": failures,
        "scope": "Read-only, synthetic local committed CP2 runs only",
        "warnings": ["Historical warehouse orders may have changed after a run", "No Spark job is executed", "When no committed runs exist, only CP3 unit/integration tests establish behavior"],
        "runs": outputs,
    }
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k != "runs"},indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
