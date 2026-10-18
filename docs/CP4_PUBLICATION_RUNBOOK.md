# Project 15 — Publication runbook and precise screenshot triggers

Status: locally validated, but NOT published. User-approved decisions: MIT license; Azure architecture documentation only (no deployment, account access or cost). These instructions use Windows PowerShell from the Project 15 directory and GitHub CLI (`gh`). Never paste API keys or `.env` into terminal output/screenshots.

## Phase 1 — Local staged security gate (STOP before push)

Download/extract the `Project15_CP4_Publication_Update.zip` **over the existing Project 15 folder** to its parent directory, retaining existing `.venv`, real evidence screenshots, outputs and local `.env`. The ZIP contains only changed/new release files and does not include credentials or screenshots.

```powershell
$project = 'C:\Users\Jonny Fernandez\Documents\github files\15_enterprise_ai_automation'
$zip = Join-Path $env:USERPROFILE 'Downloads\Project15_CP4_Publication_Update.zip'
if (-not (Test-Path -LiteralPath $zip)) { throw 'Publication ZIP missing in Downloads.' }
Expand-Archive -LiteralPath $zip -DestinationPath (Split-Path -Path $project -Parent) -Force
Set-Location -LiteralPath $project
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare_cp4_publication.ps1
```

Expected **staged Git-index audit**: `inspection_mode=git_index`, `findings=0`, six staged numbered PNGs, no `.env`, raw data, Parquet, ZIP, SQLite, Hadoop helpers or generated artifacts. Read the printed `git diff --cached --stat` and `git status --short` before proceeding. **Send the audit output to ChatGPT for review. Do not push yet.** This is separate from the earlier candidate-file audit (76 paths, zero findings).

## Phase 2 — Commit and create/push public GitHub repo (ONLY after Phase 1 is reviewed)

```powershell
gh auth status
git config user.name
git config user.email
git branch --show-current
git status --short
```

If `git config user.name` or `user.email` is empty, set your own Git identity locally; do not use guessed values. Ensure you are in the Project 15 folder and the staged index audit has passed.

```powershell
git commit -m "Publish Project 15 synthetic integration platform"
if ($LASTEXITCODE -ne 0) { throw 'Commit failed.' }
gh repo create jonny-fernandez/15_enterprise_ai_automation --public --source . --remote origin
if ($LASTEXITCODE -ne 0) { throw 'GitHub repository creation failed. Do not push until diagnosed.' }
git push -u origin main
if ($LASTEXITCODE -ne 0) { throw 'Git push failed.' }
```

If GitHub reports that the repo already exists, STOP and inspect the existing remote before any push. Do not use `--force` or overwrite an existing remote. After push, verify the commit SHA with `git rev-parse HEAD` and the repository URL with `gh repo view --web`. A successful push alone is not successful CI.

## Phase 3 — CI jobs: screenshots 07 and 08 (ONLY after real success)

Locate the current workflow run:

```powershell
gh run list --repo jonny-fernandez/15_enterprise_ai_automation --workflow ci.yml --limit 5
```

Choose the run for the commit you pushed and replace `<RUN_ID>` with its actual numeric ID:

```powershell
$runId = '<RUN_ID>'
gh run watch $runId --repo jonny-fernandez/15_enterprise_ai_automation --exit-status
if ($LASTEXITCODE -ne 0) { throw 'GitHub CI failed; investigate and repair before screenshots.' }
gh run view $runId --repo jonny-fernandez/15_enterprise_ai_automation
```

**Screenshot #07 — Ubuntu CI success.** First inspect the job list and logs. Run:

```powershell
gh run view $runId --repo jonny-fernandez/15_enterprise_ai_automation --web
```

In the GitHub Actions browser tab, select `ubuntu-full-spark`. Only after its own job page shows **Success**, take the screenshot with **Win+Shift+S**, then save the original capture as `screenshots/07_github_ubuntu_ci.png`. Include the visible job title and successful status; the Ubuntu job should include the actual Spark test.

**Screenshot #08 — Windows CI success.** On that SAME GitHub Actions run, open `windows-policy-tests`. Only after its page shows **Success**, take a separate screenshot using **Win+Shift+S** and save as `screenshots/08_github_windows_ci.png`. This hosted job deliberately **deselects** the native Hadoop Spark test: the independent actual Windows local validation (139/139) covered it. Do not misrepresent Windows hosted CI as a full native Spark test.

Verify exact screenshots locally:

```powershell
Get-ChildItem .\screenshots -Filter '*.png' | Sort-Object Name | Select-Object Name
```

If a CI job fails, do **not** capture a screenshot labeled as success. Upload the failed GitHub Actions log/output for repair; only commit real success evidence after a successful rerun.

## Phase 4 — Final security audit, evidence update, publication closure

Screenshots 07–08 do not yet exist and are not part of the first commit. Once both have been captured, re-stage those **two files only**, repeat the Git-index audit, then commit and push them:

```powershell
git add -- screenshots/07_github_ubuntu_ci.png screenshots/08_github_windows_ci.png
$env:PYTHONPATH = Join-Path (Get-Location).Path 'src'
.\.venv\Scripts\python.exe scripts/audit_cp4.py --root . --output artifacts/cp4_staged_audit.json
if ($LASTEXITCODE -ne 0) { throw 'Staged evidence audit failed.' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Staged diff check failed.' }
git diff --cached --stat
# Inspect staged paths before proceeding.
```

The runbook stops short of automatically publishing screenshots: show the audit/output first. After evidence is committed/pushed, verify actual CI for the final pushed commit, update the offline Word evidence handoff with the two real images, and **only then** close Project 15 and update the offline master resume with measured, truthful outcomes. No live Azure deployment is implied.
