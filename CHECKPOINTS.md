# Consolidated Delivery Gates (planning only)

- [x] **Consolidated CP1**: Original CP1–CP3 — validated on user Windows Python 3.12, 35/35 tests passed, 8 synthetic accepted and 0 quarantined (user-supplied manifest, 2026-10-17).
- [x] **Consolidated CP2**: Original CP4–CP11 — validated on user Windows Python 3.12, Java 17 and real Spark; 70 passed, 0 failed, 3 Parquet rows, 0 incremental replay rows (screenshots shared 2026-10-17).
- [x] **Consolidated CP3**: Original CP12–CP16 and CP18 — Windows Python 3.12 tests: 128 passed / 0 skipped (screenshots received 2026-10-18); four synthetic events and five attempts, no external writes or LLM calls. OAuth/live queues/providers intentionally not claimed.
- [ ] **Consolidated CP4**: Original CP17 and CP19 — read-only release audit + CI candidate packaged; Azure architecture-only and MIT decisions approved; six screenshots saved and Windows CP4 (139 tests, zero skips) validated. Actual Git-index audit, GitHub publication and CI remain pending.

The numbered original CP1–CP19 below are preserved for traceability. Checkmarks for CP1–CP11 represent validated **local synthetic** equivalents, not live enterprise integrations. A candidate is not complete before user Windows evidence.

---

# Project 15 Checkpoints

- [x] CP1 — Repository, workflow/data contracts, baseline tests
- [x] CP2 — Mock enterprise APIs and adapter contracts
- [x] CP3 — Raw ingestion and audit metadata
- [x] CP4 — PySpark local transformation pipeline
- [x] CP5 — Parquet partitioning, schema validation, and data-quality checks
- [x] CP6 — Incremental processing / watermark logic
- [x] CP7 — Warehouse load and reconciliation
- [x] CP8 — Deterministic workflow engine
- [x] CP9 — Scheduled workflow
- [x] CP10 — Webhook/event-driven workflow
- [x] CP11 — API-triggered workflow
- [x] CP12 — local API-key auth, secrets boundary, local pagination and rate limits (no OAuth)
- [x] CP13 — Retry/backoff/timeout/idempotency
- [x] CP14 — local SQLite queue + dead-letter handling
- [x] CP15 — deterministic mock AI escalation + validation (no LLM)
- [x] CP16 — local human-review queue (no external writes)
- [ ] CP17 — Azure deployment/integration **not implemented** (scope explicitly approved as architecture-only; see docs/CP4_AZURE_BOUNDARY.md)
- [x] CP18 — local operational metrics and synthetic end-to-end reliability tests
- [ ] CP19 — Final screenshots and GitHub handoff
