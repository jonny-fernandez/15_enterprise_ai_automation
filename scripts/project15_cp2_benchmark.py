"""Synthetic-only bounded CP2 planning benchmark (NOT a Spark throughput test)."""
import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path

# Works from any cwd, including Windows PowerShell launched inside CP2_Upgrade.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from enterprise_automation.pipelines.cp2_pipeline import _enrich
from enterprise_automation.pipelines.cp2_upgrade import dependent_order_ids
from enterprise_automation.pipelines.ingestion import canonical_json, sha256_text


def generate_synthetic_snapshot(*, customers=200, orders=2000, tickets=1000, seed=1502):
    """Generate bounded reproducible, fictional records only; no files or API calls."""
    for count in (customers, orders, tickets):
        if type(count) is not int or count < 1 or count > 50_000:
            raise ValueError("Synthetic row counts must be integers in 1..50000")
    if type(seed) is not int or not 0 <= seed <= 2**32-1:
        raise ValueError("Seed must be uint32")
    rng = random.Random(seed)
    now = "2026-10-27T00:00:00Z"
    data = {"ERP": [], "CRM": [], "TICKETING": []}
    def add(system, id, payload):
        data[system].append({"record_id": id, "payload": payload,
                             "record_sha256": sha256_text(canonical_json(payload))})
    for i in range(customers):
        cid = f"C{i:05d}"
        add("CRM", cid, {"customer_id": cid, "customer_name": f"Synthetic Customer {i:05d}",
                         "updated_at_utc": now})
    for i in range(orders):
        oid = f"O{i:06d}"
        cid = f"C{rng.randrange(customers):05d}"
        add("ERP", oid, {"order_id": oid, "customer_id": cid,
                         "amount_usd": f"{rng.randint(100,100000)/100:.2f}", "updated_at_utc": now})
    for i in range(tickets):
        tid = f"T{i:06d}"
        cid = f"C{rng.randrange(customers):05d}"
        add("TICKETING", tid, {"ticket_id": tid, "customer_id": cid,
                               "priority": "normal", "updated_at_utc": now})
    return data


def benchmark(*, customers=200, orders=2000, tickets=1000, seed=1502) -> dict:
    data = generate_synthetic_snapshot(customers=customers, orders=orders, tickets=tickets, seed=seed)
    start = time.perf_counter()
    enriched, quality = _enrich(data)
    elapsed = time.perf_counter() - start
    # A single accepted CRM update must affect exactly the subset of related ERP orders.
    selected = {"ERP": [], "CRM": [data["CRM"][0]], "TICKETING": []}
    ids = dependent_order_ids(data, selected)
    digest = hashlib.sha256(canonical_json(enriched).encode("utf-8")).hexdigest()
    return {"schema_version": "project15.cp2.synthetic-benchmark.v1",
            "execution_mode": "local_synthetic_python_only", "seed": seed,
            "customers": customers, "orders": orders, "tickets": tickets,
            "enriched_orders": len(enriched), "orders_affected_by_first_customer": len(ids),
            "quality": quality, "deterministic_result_sha256": digest,
            "elapsed_seconds": round(elapsed, 6),
            "limitations": ["in-process Python planning only", "not a Spark or cloud throughput metric",
                            "timing is machine-dependent", "no production connectors"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders", type=int, default=2000)
    parser.add_argument("--customers", type=int, default=200)
    parser.add_argument("--tickets", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1502)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = benchmark(customers=args.customers, orders=args.orders, tickets=args.tickets, seed=args.seed)
    display = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(display, encoding="utf-8")
    print(display)


if __name__ == "__main__":
    main()
