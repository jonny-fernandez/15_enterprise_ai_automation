# Project 15 — Exact CP4 screenshot evidence plan

**Screenshots 01–06: confirmed saved on user Windows on 2026-10-18; genuine image evidence embedded in offline Word handoff.** Screenshots 07–08: capture actual GitHub Actions outcomes only after publication. Do not synthesize successful CI screens or include sensitive credentials.

| Exact PNG filename | Capture genuine evidence of | Gate |
| --- | --- | --- |
| `01_cp1_ingestion_manifest.png` | CP1 accepted/quarantined counts across ERP, CRM and ticketing, synthetic-only | A |
| `02_cp2_spark_parquet.png` | Real Windows Spark test / partitioned Parquet readback, 3 orders | A |
| `03_cp2_incremental_replay.png` | CP2 new incremental ERP rows = 0, replay integrity | A |
| `04_cp3_tests_passed.png` | 128 passed, 0 skipped; full actual Windows test output | A |
| `05_cp3_reliability_evaluation.png` | Local event / attempt / dead-letter / rejected review counts | A |
| `06_cp4_security_audit.png` | CP4 read-only audit mode, findings and local pytest gate | A |
| `07_github_ubuntu_ci.png` | Actual Ubuntu CI success **only after pushed commit** | C |
| `08_github_windows_ci.png` | Actual Windows CI outcome and explicit native Spark test exclusion **after pushed commit** | C |

Optional `09_azure_integration.png` *only if* an approved Azure integration is genuinely created and tested. Otherwise do not include.

**Publication sequence caveat:** The original handoff requires screenshot approval *before* GitHub push, but the two GitHub CI screenshots can exist only *after* pushing. Screenshots `01`–`06` were saved and the initial Word handoff delivered before publication. After the first successful pushed GitHub CI run, capture `07`–`08`, update the Word handoff and verify final CI. Do not claim those CI screenshots already exist.

Screenshots should not show API keys, `.env`, credentials, private user paths beyond the necessary local root, or sensitive company records. A nonblocking test-client deprecation warning may appear; retain it honestly.

**Exact CI screenshot commands and timing:** see [`CP4_PUBLICATION_RUNBOOK.md`](CP4_PUBLICATION_RUNBOOK.md). For each CI job, wait for the actual run to complete and be successful, open its job in GitHub Actions (`gh run view <run-id> --web`), capture using **Win+Shift+S**, and save the original capture at the exact filename above. If a job fails, capture/log the failure for debugging but **do not label it success**.
