"""Heuristic read-only working-tree scan; not a release Git-index blob audit."""
import json
import subprocess
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from enterprise_automation.release_audit import audit_repository

CANDIDATE_FILES = (
    "src/enterprise_automation/pipelines/cp2_pipeline.py",
    "src/enterprise_automation/pipelines/spark_transform.py",
    "src/enterprise_automation/pipelines/cp2_upgrade.py",
    "tests/test_cp2_upgrade_evolution.py",
    "scripts/project15_cp2_benchmark.py",
    "scripts/project15_cp2_candidate_audit.py",
    "src/enterprise_automation/reliability/__init__.py",
    "src/enterprise_automation/reliability/cp3_recovery.py",
    "tests/test_cp3_recovery_integrity.py",
    "scripts/project15_cp3_evidence.py",
    "scripts/project15_cp3_candidate_audit.py",
)

def main():
    git = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
    tracked = [p.decode("utf-8") for p in git.stdout.split(b"\0") if p]
    paths = sorted(set(tracked) | set(CANDIDATE_FILES))
    result = audit_repository(root, tracked_paths=paths)
    result["scope"] = "tracked plus 11 CP2/CP3 candidate paths in working tree"
    result["limitations"] = ["Pattern/filename scan only", "No staged Git blob examination", "No third-party or credential scanning", "No production cloud validation"]
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result.get("code_audit_pass") else 1

if __name__ == "__main__":
    raise SystemExit(main())
