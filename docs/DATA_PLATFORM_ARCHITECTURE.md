# Project 15 Data Platform Architecture — CP1 Implemented vs Planned

## CP1 implemented (offline synthetic only)

```text
Mock ERP API fixture ---------> SyntheticAPIAdapter ------\
Mock CRM API fixture ---------> SyntheticAPIAdapter -------+--> versioned contract validation
Synthetic ticketing CSV ------> CSVFileAdapter -----------/      |                      |
                                                             accepted                rejected
                                                                |                      |
                                                          JSONL raw zone       SHA-only quarantine
                                                                |                      |
                                                                +--> SHA256 audit manifest
```

- CP1 simulates two independent enterprise REST-style systems with read-only paginated APIs and one CSV file drop, using synthetic fixtures only.
- Contracts pin keys, required fields, types, timezone semantics and `*.v1` versions.
- Accepted records include a source-system identifier, source type, record key, contract version, run ID, ingestion timestamp, and record SHA256.
- Source files and quarantine files each have a manifest SHA256 and accepted/quarantined counts.
- Quarantine files contain **error field labels and input hashes**, not original payloads.
- A new run ID is required for each ingestion; a repeated run ID is rejected to protect existing outputs.
- CP1 `WorkflowEngine` is in-memory and deterministic; it rejects empty payloads, skips exact repeats, and sends conflicting repeats to a review-needed status. It does **not** persist review queues or run state yet.
- `/work` fails closed until `PROJECT15_API_KEY` is provided; this **is not enterprise-grade OAuth/RBAC**.

## Later checkpoints (not implemented)

- **CP2 / original CP4–11**: PySpark transformations, partitioned Parquet, schema evolution strategy, checkpointed incremental watermarks, referential reconciliation, PostgreSQL warehouse, scheduled/event/API-triggered execution, durable idempotency.
- **CP3 / original CP12–16,18**: API credential scopes, provider auth, distributed backoff, queues/dead letter, selective AI and human-review workflows, measured reliability evaluation.
- **CP4 / original CP17,19**: justified Azure services, deployment only after approval, CI, technical/security and license audit, screenshot handoff and GitHub publication.

No Spark, database, queue, Azure, paid model or real remote integration is demonstrated by CP1.

## CP2 candidate (awaiting real Windows Spark validation)

```text
CP1 ERP / CRM / Ticketing files -- SHA + contract verification
                 |
            Spark DataFrame joins ---- compare with independent Python oracle
                 |                           |
             Parquet                   quality / orphan counts
      [event_date partition]                  |
                 +---------------------------+
                 |
       SQLite warehouse + atomic watermarks / record versions / run audit
                 |
           API / event / schedule-labelled CLI triggers (local only)
```

- Source manifests point to fixed paths under the chosen local root; path injection and raw hash mismatches are rejected.
- Incomplete Parquet files are never considered committed until SQLite run audit succeeds. Uncommitted local output is rebuilt on retry.
- CP2's SQLite transaction protects the warehouse and watermarks together. Parquet and SQLite are not a distributed transaction. An interrupted filesystem operation can require manual recovery.
- Incremental processing detects new ERP record versions within an adjustable lookback, but CRM/ticket-only changes **do not** automatically re-materialize historical ERP orders. Full refresh resolves this limitation for the supplied current snapshot.
- All operations target local synthetic files; no automated external scheduling, live PostgreSQL, queue, Azure, production permissions or networked source is tested.
