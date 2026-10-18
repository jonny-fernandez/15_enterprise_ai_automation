"""Repeatable, synthetic-only CP3 reliability evaluation; no external actions."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from enterprise_automation.governance.queue import LocalQueue
from enterprise_automation.governance.policy import canonical

SCENARIO_LOCK_SHA256 = "b35cfab29fa2546899615a1e228b8655e50772d9716dc29120baf80b3e238bcd"

SCENARIOS = (
    {"event_id":"ok_01","source":"ERP","record_ref":"order_A","scenario":"success","reason_code":"unmatched_entity"},
    {"event_id":"retry_02","source":"CRM","record_ref":"customer_B","scenario":"transient","reason_code":"timeout"},
    {"event_id":"dead_03","source":"TICKETING","record_ref":"ticket_C","scenario":"permanent","reason_code":"source_outage"},
    {"event_id":"review_04","source":"FINANCE","record_ref":"invoice_D","scenario":"review","reason_code":"duplicate_conflict"},
)


def evaluate(root: Path, run_id: str) -> dict:
    if not run_id.isascii() or not run_id.replace('_','').replace('-','').isalnum() or not 1 <= len(run_id) <= 64:
        raise ValueError('Invalid run ID')
    root = Path(root).resolve()
    artifact = root / 'artifacts' / f'{run_id}_cp3_manifest.json'
    database = root / 'artifacts' / f'{run_id}_cp3_queue.sqlite'
    if artifact.exists() or database.exists():
        raise FileExistsError('Run ID already used: manual review required')
    observed_lock = hashlib.sha256(canonical({"scenarios":SCENARIOS}).encode()).hexdigest()
    if observed_lock != SCENARIO_LOCK_SHA256:
        raise ValueError("CP3 evaluation fixture lock mismatch")
    started = time.perf_counter()
    queue = LocalQueue(database)
    events = []
    try:
        for scenario in SCENARIOS:
            assert queue.enqueue(scenario) == 'enqueued'
        duplicate = queue.enqueue(SCENARIOS[0])
        for tick in (0, 1, 2, 3, 4, 5, 6, 7, 8):
            while True:
                outcome = queue.process_one(tick)
                if outcome is None:
                    break
                events.append(outcome)
                # A leased, exhausted item is only handled once.
        queue.decide('review_04', 'reject', 9)
        counts = queue.counts()
        stats = queue.snapshot()
        assert (counts['completed'], counts['dead_letter'], counts['review_rejected']) == (2, 1, 1)
        assert stats['total_events'] == 4 and stats['review_decisions'] == 1
        assert stats['total_attempts'] == 5  # 1 success + 2 transient + 1 permanent + 1 review
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        summary = {"schema_version":"cp3.manifest.v1", "run_id":run_id,
            "execution_mode":"offline_synthetic", "model_calls":0, "external_writes":0,
            "input_fixture_sha256":observed_lock,
            "observed":stats, "duplicate_delivery":duplicate,
            "retry_schedule":"logical_ticks_not_wall_clock", "evaluation_events":events,
            "measured_local_ms":duration_ms,
            "limitations":["local single-worker SQLite", "no live OAuth, providers or LLMs",
                           "logical retry/timeout simulations, not network fault injection",
                           "review approval is local bookkeeping; never an external mutation"]}
        artifact.write_text(json.dumps(summary, indent=2, sort_keys=True)+"\n", encoding='utf-8')
        return summary
    finally:
        queue.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(Path(args.root), args.run_id), indent=2, sort_keys=True))
    print(f'CP3 evidence: artifacts/{args.run_id}_cp3_manifest.json')


if __name__ == '__main__':
    main()
