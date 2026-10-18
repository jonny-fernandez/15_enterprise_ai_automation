# Stages allowlisted Project 15 publication files; does NOT commit, push or deploy.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is not installed or not in PATH.' }
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Project 15 validated .venv is missing.' }
$env:PYTHONPATH = Join-Path $root 'src' # Required for src-layout release_audit imports.

if (-not (Test-Path -LiteralPath (Join-Path $root '.git'))) {
    & git init -b main
    if ($LASTEXITCODE -ne 0) { throw 'Git initialization failed.' }
    Write-Host 'Initialized a LOCAL Git repository. No remote or publication was created.'
} else {
    Write-Host 'Existing local Git repository detected.'
}

$paths = @(
    '.env.example', '.gitattributes', '.gitignore', '.github/workflows/ci.yml',
    'LICENSE', 'README.md', 'CHECKPOINTS.md', 'PROJECT_PLAN.md',
    'PROJECT_RULES.md', 'UPDATES_FROM_JOB_REVIEW.md', 'pyproject.toml',
    'requirements.txt', 'requirements-cp1.txt', 'requirements-cp2.txt',
    'docs', 'scripts', 'src', 'tests', 'data/fixtures', 'screenshots',
    'artifacts/.gitkeep', 'data/raw/.gitkeep', 'data/processed/.gitkeep',
    'logs/.gitkeep', 'outputs/.gitkeep'
)
foreach ($path in $paths) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $path))) {
        throw "Expected publication file or directory missing: $path"
    }
    & git add -- $path
    if ($LASTEXITCODE -ne 0) { throw "Git staging failed at: $path" }
}

& $python scripts/audit_cp4.py --root $root --output artifacts/cp4_staged_audit.json
if ($LASTEXITCODE -ne 0) { throw 'Blocking finding in actual Git-index security audit.' }
$report = Get-Content -LiteralPath (Join-Path $root 'artifacts/cp4_staged_audit.json') -Raw | ConvertFrom-Json
if ($report.inspection_mode -ne 'git_index' -or $report.finding_count -ne 0) {
    throw 'Git-index security gate did not pass.'
}
& git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Staged whitespace/conflict-marker check failed.' }
$names = @(& git diff --cached --name-only)
if ($LASTEXITCODE -ne 0 -or $names.Count -lt 60) { throw 'Unexpectedly small or invalid staging set.' }
$images = @($names | Where-Object { $_ -match '^screenshots/0[1-6]_.+\.png$' })
if ($images.Count -ne 6) { throw "Expected 6 original screenshots staged, observed $($images.Count)." }
Write-Host ''
Write-Host 'STAGED PUBLICATION GATE: PASSED' -ForegroundColor Green
Write-Host "Git index scanned: $($report.inspected_paths) paths; security findings: $($report.finding_count)"
Write-Host "Staged original screenshot PNGs: $($images.Count)"
Write-Host '---- STAGED SUMMARY ----'
& git diff --cached --stat
Write-Host '---- GIT STATUS ----'
& git status --short
Write-Host ''
Write-Host 'STOP HERE. Review these staged paths and send this result before committing/pushing.' -ForegroundColor Yellow
Write-Host 'No GitHub repository was created and nothing was pushed.'
