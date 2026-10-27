"""Scan tracked Project 15 files plus explicitly declared CP2 candidate files."""
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
)

def run():
    git = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                         capture_output=True, check=True)
    tracked = [s.decode("utf-8") for s in git.stdout.split(b"\0") if s]
    candidate = sorted(set(tracked) | set(CANDIDATE_FILES))
    report = audit_repository(root, tracked_paths=candidate)
    report["scope"] = "tracked plus six explicitly declared CP2 candidate paths (working tree)"
    report["candidate_paths"] = list(CANDIDATE_FILES)
    report["warning"] = "Heuristic working-tree audit; not a final staged Git-blob audit."
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["code_audit_pass"] else 1

if __name__ == "__main__":
    sys.exit(run())
