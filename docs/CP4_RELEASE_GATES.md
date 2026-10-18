# CP4 — Verified release gates and required evidence

This CP4 package creates a **prepublication candidate**, not a published repository. It preserves CP1–CP3 and does not install infrastructure, call Azure, commit, push, or deploy.

## Gate A — Windows local release validation

Run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_cp4.ps1` from the Project 15 folder. The script reuses the tested JDK 17, Hadoop helpers and `.venv`, executes full local pytest (real Spark required), and runs a read-only candidate/track-path security audit. The required test count is **at least 139**, with zero failures or skips. **Observed on user Windows 2026-10-18: 139 passed, 0 failures, 0 skips, 1 nonblocking warning.**

The audit report is generated at `artifacts/cp4_repository_audit.json`. Before Git is initialized, the report says `candidate_files_without_git` and is **not equivalent to a Git-index or secret-scanning release sign-off**. Re-run after staging and before any push; all findings must be resolved.

## Gate B — Azure/enterprise architecture decision (approved)

See `docs/CP4_AZURE_BOUNDARY.md`. The user approved **architecture-only** Azure mapping and no cloud costs. No Azure resources have been deployed; a separate authorization is required for any future live service creation. Original live CP17 remains unimplemented under this approved architecture-only scope; do not manufacture deployment metrics.

## Gate C — Cross-platform GitHub CI

A `.github/workflows/ci.yml` candidate is provided. **It has not run on GitHub.** Ubuntu is designed to run the full suite including Spark; Windows-hosted CI deliberately excludes the real native-Hadoop Spark test, which requires third-party executables. The user's actual Windows local gate covers that test. The CI output explicitly labels the Windows exclusion; it is never called a full Windows integration pass.

Do not stage or push until the screenshot handoff and user confirmation. After publication, verify the actual pushed commit and GitHub Actions result for both matrix jobs, and fix any failures before closing.

## Gate D — Genuine screenshots and offline Word handoff

`docs/SCREENSHOT_PLAN.md` defines exact PNG names. Capture **true** outputs; do not fabricate. Once the screenshots are supplied, a Word document embedding those originals plus filenames and descriptions will be delivered *before* any GitHub publication. Wait for the user's confirmation that numbered PNG files are stored under `/screenshots`.

## Gate E — Publication audit and resume

Before staging, recheck `.gitignore`, repository file inventory, staged and tracked paths, secrets, licenses and generated output. No `.env`, real tokens, generated SQLite/Parquet, cloud credentials, community Hadoop executables, logs or unredacted traces are permitted. `LICENSE` is included under the user-approved MIT license. Do not update the master resume until release is actually published and both CI checks have finished successfully.

Evidence sources: user Windows CP1 35 passed; Windows CP2 70 passed; Windows CP3 **128 passed, 0 skipped**; Windows CP4 **139 passed, 0 skipped, 0 audit findings** on 2026-10-18; 6 genuine screenshots saved, offline Word handoff delivered. CP3 evaluation is synthetic only. Actual Git-index audit, remote CI and GitHub publication are pending. Azure is deliberately documentation only.

## Gate F — Final staged-index and screenshot protocol

Run `scripts/prepare_cp4_publication.ps1` **after extracting the publication update**. It initializes Git only if needed, explicitly stages a reviewed set of source/docs/fixtures/screenshots (not broad `git add -A`), runs the actual **Git-index** audit, and prints the staged summary. It does **not** commit, push, or access Azure. Review its output **before** the separate commit/push commands in `docs/CP4_PUBLICATION_RUNBOOK.md`. Capture only genuinely successful job results for screenshots `07_github_ubuntu_ci.png` and `08_github_windows_ci.png`.
