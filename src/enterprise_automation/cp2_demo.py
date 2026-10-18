"""Offline CP2 entry point: actual local Spark + local SQLite.

Example:
 python -m enterprise_automation.cp2_demo --root . --source-run-id cp1_demo --run-id cp2_demo
"""
import argparse
import json
import os
from pathlib import Path
import sys

from enterprise_automation.pipelines.cp2_pipeline import execute_cp2


def local_spark():
    try:
        from pyspark.sql import SparkSession
    except ImportError as exc:
        raise RuntimeError("Install requirements-cp2.txt; PySpark is mandatory for CP2") from exc
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
    return (SparkSession.builder.master("local[2]")
            .appName("Project15CP2Synthetic")
            .config("spark.ui.enabled", "false")
            .config("spark.driver.bindAddress", "127.0.0.1")
            .config("spark.sql.session.timeZone", "UTC")
            .getOrCreate())


def main():
    parser = argparse.ArgumentParser(description="CP2 local Spark synthetic demo")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--trigger-mode", choices=["scheduled", "event", "api", "manual"], default="manual")
    parser.add_argument("--trigger-id")
    parser.add_argument("--load-mode", choices=["full", "incremental"], default="incremental")
    args = parser.parse_args()
    spark = local_spark()
    try:
        result = execute_cp2(root=args.root, source_run_id=args.source_run_id,
            run_id=args.run_id, trigger_mode=args.trigger_mode, trigger_id=args.trigger_id,
            load_mode=args.load_mode, spark=spark)
    finally:
        spark.stop()
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Local synthetic only: no real PostgreSQL, API providers, queues, cloud or paid AI.")


if __name__ == "__main__":
    main()
