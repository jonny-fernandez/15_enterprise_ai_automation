# CP3 — Security, Queue and Reliability Evidence Gate (Candidate)

**CP3 is pending real Windows validation.** CP1 and CP2 passed on the user's Windows host. The CP3 candidate adds local synthetic governance, not live enterprise systems, OAuth, cloud services, LLM calls, or production integrations.

## Validated inputs / dependencies

- Start from the previously tested CP2 Windows environment: Python 3.12 project `.venv`, OpenJDK 17.0.20.1, local PySpark 4.0.4 and the Windows Hadoop 3.4.1 native helper files already installed under `%LOCALAPPDATA%\Project15\hadoop-3.4.1\bin`.
- Extract `Project15_CP3_Replacement.zip` into the *parent* of the current Project 15 folder (preserve the existing `.venv`, `.env` and generated data).
- Do not install or set up external services. No production credentials are needed. CP3 API tests inject throwaway synthetic test keys via pytest; those values are not real secrets.

## One-step Windows validation

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_cp3.ps1
```

The PowerShell script detects the existing Java and Hadoop files, points Spark worker processes at the existing Python `.venv`, runs every test (including real Spark), checks for **no failures and no skipped tests**, and executes a new synthetic CP3 demo. It does not reinstall Java, Spark, Python, system tools or the CP2 environment.

## Acceptance evidence

1. The pytest summary reports all tests passed and **0 skipped**. The local development machine ran 127 passed / 1 skipped because the real-Spark test was unavailable; do not confuse it with a Windows passing Spark gate. Test counts may rise when defects are fixed.
2. The output identifies `CP3 completed; evidence: artifacts/<run_id>_cp3_manifest.json`.
3. The manifest reports `execution_mode=offline_synthetic`, `model_calls=0`, `external_writes=0`, `input_fixture_sha256=b35cfab29fa2546899615a1e228b8655e50772d9716dc29120baf80b3e238bcd` and real (local) `measured_local_ms`.
4. The report confirms four synthetic event IDs, `duplicate_delivery=duplicate_skipped`, `total_attempts=5`, `total_events=4`, `review_decisions=1`, `completed=2`, `dead_letter=1`, `review_rejected=1`.
5. Verify negative tests include malformed IDs and event fields, unsupported model statements, stale queue claims, unauthorized API scopes, duplicate conflicts, failure/retry and manual approval/rejection.
6. Send the **final test summary** plus `artifacts/<run_id>_cp3_manifest.json` (a synthetic, redacted metadata-only file). Do not upload `.env` or its contents.

## Exact scope and caveats

The CP3 queue is a local single-worker SQLite proof of design, using exclusive transactions and claim leases for recovery. Exponential backoff and timeouts are modeled with **logical ticks**, not OS-enforced execution timeouts; simulated transient failures do not measure external network reliability. Manual approval controls local review state only: it does not execute or approve any live write. A mock "AI" returns allowed structured proposals; no genuine language model, RAG, external API or AI accuracy measurement is involved.

Distinct operator and reviewer API keys, local per-process rate limiting and metadata pagination are demonstrated by unit tests. They are **not** enterprise OAuth, centralized authentication, distributed quotas or provider pagination. The existing warehouse uses SQLite, not PostgreSQL or Azure. These limitations remain blocking for any real production deployment claim. CP4 still requires screenshots, CI, security audit, user confirmation before publication, and any Azure work approved separately.

## File safety

No `.env`, personal data, `winutils.exe`, `hadoop.dll`, generated database or Parquet data belongs in Git. `.gitignore` protects local output, but inspect actual tracked/staged files again at CP4. A validated hash of the Windows native archive identifies its community asset only and does not guarantee the publisher's trustworthiness.
