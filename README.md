# Project 15 — Enterprise AI Automation & Distributed Data Integration Platform

**Status (2026-10-18): CP1–CP4 locally validated on Windows (CP4: 139/139 tests, zero skips; candidate audit: 76 paths, zero findings). Screenshots 01–06 confirmed saved. MIT license approved; Azure architecture-only scope approved. Initial Git staging, publication and GitHub CI are still pending.** The portfolio project demonstrates proposed enterprise integration patterns **with synthetic local fixtures only**. It does not connect to real enterprise systems.

## What is implemented in CP1

- Versioned deterministic source contracts for simulated ERP orders, CRM customers and ticketing CSV records.
- Synthetic paginated ERP/CRM FastAPI mock endpoints; deterministic local paged adapters; CSV file adapter.
- Raw JSONL landing with record-level SHA256, run-level manifests, source version/provenance, counts, and hash-only quarantine of invalid rows.
- Safe validation: unexpected field, missing field, negative/invalid financial amount, bad UTC timestamp, duplicate record ID.
- Local workflow idempotency with content conflict detection and rejected empty payloads.
- Fail-closed `/work` endpoint requiring explicitly configured `PROJECT15_API_KEY`; unrestricted local `/health` endpoint.
- CP1-only dependency list and PowerShell setup / testing script. Later PySpark, Azure and enterprise auth are **not** complete.

## Windows CP1 validation

```powershell
# From C:\Users\Jonny Fernandez\Documents\github files\15_enterprise_ai_automation
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_cp1.ps1
```

The command creates `.venv` (Python 3.12), installs only small CP1 packages, runs pytest, and writes a synthetic `data/raw/<run_id>` directory and `artifacts/<run_id>_cp1_manifest.json`. Keep `.env` private. Review [`docs/CP1_VALIDATION.md`](docs/CP1_VALIDATION.md) for required evidence and limitations.

## Source and execution contracts

See [`docs/INTEGRATION_CONTRACTS.md`](docs/INTEGRATION_CONTRACTS.md), [`docs/DATA_PLATFORM_ARCHITECTURE.md`](docs/DATA_PLATFORM_ARCHITECTURE.md), original [`PROJECT_PLAN.md`](PROJECT_PLAN.md), and original [`CHECKPOINTS.md`](CHECKPOINTS.md).

## CP1 acceptance is not a production deployment

Tests and local synthetic ingestion cannot establish real API connectivity, scalable distributed throughput, production availability, cloud cost, business data reconciliation or OAuth security. The architecture roadmap retains Spark/Parquet, incremental processing, warehouse, durable workflows, selective AI, human approval and Azure integration for later checkpoints.

## CP2 — Windows-validated local Spark/Parquet platform

CP1 and CP2 are complete at their local synthetic evidence gates. CP2 implements a **synthetic-only local** processing workflow with:

- Spark DataFrame joins across ERP orders, CRM customers and ticketing references, checked against an independent deterministic reference implementation.
- Typed money fields (`Decimal(18,2)`), UTC event-date partitioned Parquet, Parquet byte hashes, full-refresh and incremental selection.
- Source manifest/hash checks, per-source watermarks, a one-day configurable late-arrival lookback, and record-version deduplication.
- Local **SQLite** warehouse with atomic run/warehouse/watermark commits, input/trigger replay protection, incomplete-output reconstruction, and unmatched-reference scorecards.
- API-key-gated local API (`/cp2/run`) and synthetic event (`/cp2/event`) endpoints. A "scheduled" CLI invocation models execution by an external scheduler; **no automatic background scheduler has been installed**.

### Windows CP2 setup + validation

```powershell
# From Project 15 root after extracting the CP2 replacement ZIP to its parent:
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_cp2.ps1
```

**Prerequisites:** Existing CP1 `.venv`, compatible Java JDK on PATH, and internet access to install CP2 PySpark dependencies. The script does not install Java, run real APIs, touch cloud resources, or publish to GitHub. If Java is missing, the script stops before installing anything. See [`docs/CP2_VALIDATION.md`](docs/CP2_VALIDATION.md) for expected artifacts and limitations.

The source `warehouse/postgres.py` remains a deliberate, unconnected starter stub. CP2 uses SQLite locally; no PostgreSQL deployment has been made or tested. Windows CP2 evidence: 70 automated tests passed with a nonblocking httpx test-client warning, real Parquet readback of 3 synthetic ERP rows, a local SQLite commit, and 0 new ERP records on the incremental replay. No real Azure, production authentication or distributed service deployment was demonstrated.


## CP3 — Windows-validated synthetic governance, resilience and reliability

The CP3 implementation adds a **local, deterministic** operational safety layer. It is not a cloud-native broker or a production OAuth integration:

- Strict synthetic event contracts and unknown-field rejection (including unexpected PII-bearing fields). Source identities are bounded references, not personal records.
- Separate `operator` and `reviewer` API keys injected at run time; equality checks are constant-time. Both keys must be configured, distinct, and nonempty. An in-memory, single-process rate limiter protects CP3 API routes.
- Durable single-worker SQLite queue with event-ID/content deduplication, claim leases, crash recovery, finite attempts, simulated exponential tick-based backoff, dead-letter states, and immutable review decisions.
- Deterministic mock "AI" proposals carry validated evidence hashes and allowed reason codes. **No live AI model is called** and no proposal becomes an external write. A different reviewer credential must decide approve/reject.
- Local API `/cp3/event`, `/cp3/process`, `/cp3/events` (bounded metadata pagination), `/cp3/metrics` and `/cp3/review/{event_id}`. No internet services or production connectors are used.
- Locked, synthetic CP3 evaluation: four distinct events (success, recoverable transient, permanent failure, human review), one duplicate delivery, two completed, one dead-letter, one explicitly rejected review, five total attempts, and measured *local* execution time. Tampered model proposals and access denials are negative-test cases.

### Windows CP3 validation

Prerequisites: the **existing CP2-passing** `.venv`, JDK 17 and Hadoop helpers. Extract the CP3 ZIP over the Project 15 folder just as with CP2, then run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_cp3.ps1
```

The validation script installs nothing: it reuses the established CP2 environment, runs the entire CP1/CP2/CP3 test suite **including actual Spark** and enforces zero skipped tests, then produces `artifacts/<run_id>_cp3_manifest.json`. See [`docs/CP3_VALIDATION.md`](docs/CP3_VALIDATION.md).

### Limits and pending scope

The queue is SQLite, single-host and synthetic, not Azure Service Bus, a live queue, a background scheduler, or an exactly-once distributed system. Backoff/timeouts are modeled with deterministic logical ticks, not network-fault or resource-cancellation measurements. API-key scope separation is **not OAuth**; provider pagination and rate limits are not measured. The "AI" is a strict deterministic mock, not a paid LLM. Approval affects only local simulated review state, with no external write. Further integration/deployment requires explicit design review and consent; none is claimed here. Windows CP3 gate completed on 2026-10-18: 128 passed, zero skipped; synthetic evidence reports 4 events, 5 attempts, 2 completed, 1 dead-lettered and 1 rejected review. The locked local fixture and queue database were separately inspected. No real service, OAuth or AI model was tested. CP4 screenshot handoff must precede GitHub publication.


## CP4 — Locally validated; publication and GitHub CI pending

CP4 adds a **read-only repository/security-pattern audit** with negative-case regression tests, a Windows full-Spark release test runner, Ubuntu/Windows GitHub Actions candidates, a screenshot plan and Azure architecture mapping. Actual Windows validation on 2026-10-18 passed **139 tests, zero failures, zero skips**; the candidate-file audit scanned 76 paths with zero findings. The six prepublication PNGs were saved and the Word evidence handoff was delivered. The project is **not yet published**, and neither actual GitHub CI nor Azure deployment has occurred.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_cp4.ps1
```

The Windows runner reuses the existing `.venv`, JDK 17 and Hadoop helpers and requires **zero skipped Spark tests**. It runs a read-only path/credential pattern audit and writes `artifacts/cp4_repository_audit.json`. A clean pattern scan does not guarantee the absence of secrets; repeat the audit on the actual Git index and perform additional human checks before publication.

See [`docs/CP4_RELEASE_GATES.md`](docs/CP4_RELEASE_GATES.md), [`docs/CP4_AZURE_BOUNDARY.md`](docs/CP4_AZURE_BOUNDARY.md), and [`docs/SCREENSHOT_PLAN.md`](docs/SCREENSHOT_PLAN.md). The original project calls for Azure; live credentials, tenancy, budget, RBAC, latency, and deployment are **not** included without separate consent.

**Release sequence:** Six numbered, genuine prepublication screenshots (01–06) have been confirmed saved. Follow [`docs/CP4_PUBLICATION_RUNBOOK.md`](docs/CP4_PUBLICATION_RUNBOOK.md): stage only allowlisted source and evidence files, audit the **actual Git index**, inspect the staged changes, then commit/publish. Capture screenshots 07 and 08 **only after** the actual Ubuntu and Windows GitHub Actions jobs succeed; update the offline Word evidence handoff after CI. The hosted Windows CI deliberately excludes the native-Hadoop Spark test; the user's 139/139 Windows test run includes it. No Azure deployment is claimed.

## License and cloud boundary

MIT-licensed (see [`LICENSE`](LICENSE)). Azure is **architecture documentation only**, by explicit project decision: no cloud account, resource deployment, paid AI service, enterprise OAuth, or real business-system connection is demonstrated. Full release steps and timed screenshot instructions are in [`docs/CP4_PUBLICATION_RUNBOOK.md`](docs/CP4_PUBLICATION_RUNBOOK.md).
