# CP1 only: creates private .venv and installs a deliberately small dependency set.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 venv creation failed' }
}
& $python -m pip install -r (Join-Path $root 'requirements-cp1.txt')
if ($LASTEXITCODE -ne 0) { throw 'CP1 dependency installation failed' }
$env:PYTHONPATH = Join-Path $root 'src'
& $python -m pytest -o addopts="" -q
if ($LASTEXITCODE -ne 0) { throw 'CP1 tests failed; ingestion not run' }
$runId = 'cp1_demo'
if ((Test-Path (Join-Path $root "data\raw\$runId")) -or (Test-Path (Join-Path $root "artifacts\${runId}_cp1_manifest.json"))) {
    $runId = 'cp1_demo_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
}
& $python -m enterprise_automation.cp1_demo --root "$root" --run-id $runId
if ($LASTEXITCODE -ne 0) { throw 'CP1 demo ingestion failed' }
Write-Host "CP1 tests and demo completed locally. Run ID: $runId"
