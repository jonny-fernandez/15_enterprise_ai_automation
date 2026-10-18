"""Run entirely offline: python -m enterprise_automation.cp1_demo --root ."""
import argparse
import json
from pathlib import Path

from enterprise_automation.adapters.synthetic import build_demo_sources
from enterprise_automation.pipelines.ingestion import ingest_sources


def main() -> None:
    parser = argparse.ArgumentParser(description="CP1 synthetic, offline ingestion")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", default="cp1_demo")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = ingest_sources(sources=build_demo_sources(root / "data" / "fixtures"),
                              root=root, run_id=args.run_id)
    print(json.dumps(manifest, indent=2))
    print("Synthetic-only; no real APIs, databases, queues, AI models, or cloud services were used.")


if __name__ == "__main__":
    main()
