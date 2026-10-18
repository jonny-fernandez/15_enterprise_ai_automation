# Consolidated CP1 Validation and Evidence Contract

Original starter checkpoints covered by this gate: **original CP1–CP3** (repository/contracts, synthetic adapters, raw ingestion and audit metadata). The original 19-checkpoint roadmap remains in `CHECKPOINTS.md`.

## Windows run

1. Extract `Project15_CP1_Replacement.zip` directly into the existing `github files` parent folder, overwriting same-named starter files. The archive does **not** contain `.env`, credentials, compiled Python or previous build outputs. Your local `.env` is preserved on extraction.
2. From PowerShell inside the Project 15 root, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_cp1.ps1`. It creates `.venv` with installed Python 3.12, installs **minimal** dependencies from `requirements-cp1.txt`, tests, and executes local synthetic ingestion.
3. Return the complete terminal output (including test count), `artifacts/cp1_demo*_cp1_manifest.json`, and optionally screenshots. If the script errors, return the exact traceback; do not claim completion.

The demo should accept **8 source rows** (ERP 3, CRM 3, ticketing 2) with no quarantines on unchanged synthetic fixtures. That is an expected fixture property, **not** a claim about your Windows environment until the script runs there. Test counts may differ as tests are added.

## Blocking success criteria

- Interpreter is Python 3.12 in Project 15's own `.venv`.
- Existing and added tests pass on Windows; report exact count and failures.
- Mock HTTP pagination and file-drop adapters demonstrate distinct source types.
- Contract validation rejects malformed records without logging input values.
- Manifest counts match landed raw JSONL rows; SHA256 hashes match file bytes.
- Same run ID cannot silently overwrite old data.
- Workflow rejects empty payload, detects changed reuse of a work ID and handles timestamp timezone offsets.
- Work API is disabled if no configured API key; an incorrect key cannot pass.
- No externally connected system, cloud deployment, paid AI or GitHub publication is claimed.

## Known limitations

- This is a *local* demo; mock API ingestion bypasses real HTTP/network reliability.
- The sample is tiny and synthetic; no real performance/scale claims.
- No persisted idempotency, resume or atomic multi-source transaction in CP1.
- No cross-source identity resolution; no referential integrity across sources yet.
- File writes can leave partial output if interrupted; recovery and durable commits are slated for CP2.
- Credential setup in CP1 is minimal fail-closed API-key authorization, not enterprise authentication.
