# CP2 Evidence Gate — Windows, Python 3.12 and Real Local PySpark

The candidate bundle should **not** be considered a passed CP2 checkpoint until the user's own Windows run succeeds. Local development validated non-Spark logic; the real PySpark integration test is intentionally skipped where Spark is unavailable.

## Expected setup

- Project path: `C:\Users\Jonny Fernandez\Documents\github files\15_enterprise_ai_automation`.
- Current CP1 `.venv` exists from successful CP1 run.
- A **compatible JDK (17 or 21)** is installed. The CP2 validation script selects it without requiring permanent PATH changes.
- **Native Windows only:** Parquet output needs Hadoop `winutils.exe` and `hadoop.dll` built for the Hadoop 3.4 line. Store them in `%LOCALAPPDATA%\Project15\hadoop-3.4.1\bin` (or point `HADOOP_HOME` to their parent). These are not bundled or silently downloaded. See the release and security notes below.
- CP2 script installs additional Python dependencies in the project's isolated `.venv` only, not the global Python environment.
- `PROJECT15_API_KEY` is not necessary for CLI validation; never place secrets in transcripts, screenshots or ZIPs.

## One command

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_cp2.ps1
```

The script checks Java, installs `requirements-cp2.txt`, executes all tests including the **actual real-Spark integration test**, and generates a new uniquely timestamped raw run, CP2 Parquet output and a second incremental no-change run.

## Expected checks and evidence

1. All tests should pass with **no Spark tests skipped**. The exact number depends on installed library versions and later regression changes. Treat any test failure as a blocked gate.
2. New source run contains **8 accepted synthetic records** (ERP 3, CRM 3, ticketing 2).
3. First CP2 run shows `rows_written_parquet = 3`, `rows_readback_parquet = 3`, `spark_join_verified = true`, `orders_matched_customers = 3`, and no unmatched ticket/customer references.
4. Second CP2 incremental run from the same immutable source should show `rows_written_parquet = 0` and `already_processed` counts of ERP 3, CRM 3, ticketing 2.
5. `data/processed/<CP2_RUN_ID>/parquet/` contains genuine Spark Parquet parts with SHA256 evidence in `cp2_manifest.json`. `artifacts/cp2_local_warehouse.sqlite` is ignored by Git.
6. Share PowerShell output and `data/processed/<CP2_RUN_ID>/cp2_manifest.json` (manifest only) for review. The outputs contain fabricated data only; do **not** upload your `.env` or any credential file.
7. If Spark reports a Java/Hadoop/Py4J error, send the **first full exception**, not just the tail; do not reinstall Python or entire development tools.

## Controls and limitations

- Only synthetic local fixture adapters, local Spark, local Parquet and SQLite are in use. Spark `local[2]` does not demonstrate distributed cluster performance.
- Scheduled mode is a real one-shot CLI invocation *labeled* with a unique schedule slot. Recurrence requires an external scheduler and is not configured here.
- API and event triggers are localhost-capable, API-key-gated routes, not production OAuth or event-broker subscriptions. Live listener traffic is not part of CLI evidence.
- Input hash and contract validation runs before transformation. Unmatched foreign keys remain visible in audit scorecards rather than being guessed away.
- Incremental selection preserves per-source versions and timestamp watermarks, but older versions beyond the lookback window are flagged and not loaded. CRM/ticket-only updates require a full refresh to rebuild existing ERP order enrichment.
- SQLite atomicity protects its own data, not a cross-system transaction with Spark filesystem output. Interrupted runs may leave uncommitted outputs, which are rebuilt after safety checks. Single-process evaluation only.
- Real PostgreSQL, queues/dead-letter infrastructure, Azure, OAuth, selective AI and production reliability remain future scope.


## Windows Hadoop native prerequisites (CP2 Windows repair)

Windows Spark 4.0.4 + Hadoop 3.4.x can fail at `.parquet()` with
`HADOOP_HOME and hadoop.home.dir are unset`. Java 17 is not the cause.
The native Windows Hadoop bridge requires **both** `winutils.exe` and
`hadoop.dll` in the same `bin` directory, with `HADOOP_HOME` pointing to
its parent directory. The validation script checks these before rerunning
tests and will not silently download or execute third-party code.

Suggested user-reviewed source (not an official Apache binary release):
https://github.com/zehelh/winutils/releases/tag/hadoop-3.4.1
Choose the **native** package matching Hadoop 3.4.1, review provenance
and execute only if you trust it. Extract the native files to:
`%LOCALAPPDATA%\Project15\hadoop-3.4.1\bin\`, or run
`scripts/prepare_cp2_windows_hadoop.ps1 -NativeZip <user-reviewed-native-zip>`
to extract only `winutils.exe` and `hadoop.dll` from your downloaded ZIP.
The helper does **not** download or run these third-party binaries.
Do not put the binaries in this Git repository. A WSL/Linux execution
environment is the alternative if external Windows binaries are not trusted.

The CP2 code also fixes a Windows-specific duplicate replay false positive:
the old check used `str(Path(...)).startswith('parquet/')`, which is false
for Windows `\` separators. Paths are now validated as portable POSIX
manifest paths with file hashes and complete file-inventory verification.
