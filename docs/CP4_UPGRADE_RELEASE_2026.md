# Project 15 - 2026 upgrade release review

Status: CP1, CP2 and CP3 have passed local verification. **The upgrades have not been published to GitHub and upgraded GitHub Actions have not yet run.**

## Scope and evidence

- Original Project 15 baseline: 139/139 passing Windows tests at baseline commit `495dcab7`.
- CP2 introduces opt-in schema compatibility, dependent-order refresh and partitioned Spark output. Full CP2 Windows verification: 171/171 passing. The 2,000-order synthetic benchmark measures local Python planning only; it is not Spark throughput.
- CP3 adds read-only recovery classification, integrity, replay and monitoring checks. Full Windows suite: **215/215 passing, zero skips** with an in-memory Spark `local[1]` override (the original project's `local[2]` remains unchanged).
- CP3 read-only inspection: two saved synthetic committed runs passed integrity and quality checks. The inspection does not represent a fresh production replay or distributed performance benchmark.
- CP3 candidate security audit: 96 paths, zero heuristic findings. A fresh **staged Git-index audit** must pass before publication.
- CP4 visual summaries (`screenshots/09_` through `14_`) were rendered from the verified results. **They are not actual terminal screenshots**. The original `01_` through `08_` screenshot files already in the repository remain separate original captures. Do not use these summaries to represent direct capture of CI.

## CI disclosure

The updated Ubuntu job requires at least 215 tests and zero skips, including native Spark. The Windows-hosted job explicitly deselects **three** environment-specific tests: native Hadoop Spark integration and two Windows symlink-permission tests, and requires at least 212 passing tests with zero skips. This is not equivalent to the 215-test administrator-run Windows validation, which is documented above.

The workflow has not run for this upgrade; CI verification is a post-push release gate. A failed run must be investigated, not described as success.

## Security and privacy

Keep `.env`, API tokens, virtual environments, `CP1_Baseline/`, `CP2_Upgrade/`, `CP3_Recovery/`, `CP4_Release/`, logs and generated Parquet/SQLite outputs out of Git. Review any already committed original screenshots for local names, usernames, or directories before publishing these modifications. The Git-index audit is a filename/heuristic text scan, not a comprehensive secret scanner.

## Publication order

1. Verify the generated summaries and documentation. Apply the CP4 documentation-only patch without staging.
2. Stage the exact 22 allowlisted upgrade paths and run the Git-index audit. **Stop and send output for review.**
3. After explicit authorization, commit and push to the existing `origin` without force pushing.
4. Verify both Ubuntu and Windows jobs at the published commit. Close CP4 only if both succeed.

## Limits

Synthetic, offline/local data only. No production ERP/CRM integration, distributed Spark throughput, or Azure deployment is claimed. A successful Windows single-worker test is not proof that the previous `local[2]` failure mechanism is permanently resolved.
